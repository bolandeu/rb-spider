"""A page's main content as Markdown — for LLMs (`spider fetch --markdown`, `include=markdown`).

Our own converter on selectolax rather than a library: it reuses the crawl's parser and its idea of
"not content" (`crawl.content_exclude`, menus and footers by default), and every rule is ours to
change. Content is `<main>` / `<article>` when the page has one, else `<body>`; scripts, forms,
sidebars and embeds never are. Headings, paragraphs, (nested) lists, links with absolute URLs,
images, tables, code, quotes and emphasis are kept; everything else becomes plain text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser, LexborNode

from .extract import DEFAULT_CONTENT_EXCLUDE

_DROP = {"script", "style", "noscript", "template", "svg", "aside", "form", "iframe", "button", "select", "input",
         "textarea", "canvas", "object", "embed", "dialog", "-comment"}  # fmt: skip
_HEADINGS = {f"h{i}": "#" * i for i in range(1, 7)}
_BLOCKS = {"p", "div", "section", "article", "main", "header", "ul", "ol", "li", "table", "pre", "blockquote",
           "hr", "figure", "figcaption", "dl", "dt", "dd", "address", "details", "summary", "body", *_HEADINGS}  # fmt: skip
_SPACES = re.compile(r"[ \t\r\n\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def html_to_markdown(body: bytes, url: str, exclude: Sequence[str] = DEFAULT_CONTENT_EXCLUDE) -> str:
    tree = LexborHTMLParser(body)
    for selector in exclude:
        for node in tree.css(selector):
            node.decompose()
    root = tree.css_first("main") or tree.css_first("article") or tree.body
    if root is None:
        return ""
    return _BLANK_LINES.sub("\n\n", _Converter(url).block(root)).strip() + "\n"


class _Converter:
    def __init__(self, url: str) -> None:
        self.url = url

    # --- blocks: each returns Markdown with blocks separated by blank lines

    def block(self, node: LexborNode) -> str:
        parts: list[str] = []
        inline: list[str] = []

        def flush() -> None:
            text = _SPACES.sub(" ", "".join(inline)).strip()
            if text:
                parts.append(text)
            inline.clear()

        for child in node.iter(include_text=True):
            tag = child.tag
            if tag in _DROP:
                continue
            if tag in _BLOCKS:
                flush()
                rendered = self._block_element(child)
                if rendered.strip():
                    parts.append(rendered.strip("\n"))
            else:
                inline.append(self.inline(child))
        flush()
        return "\n\n".join(parts)

    def _block_element(self, node: LexborNode) -> str:
        tag = node.tag
        if tag in _HEADINGS:
            text = self._inline_children(node)
            return f"{_HEADINGS[tag]} {text}" if text else ""
        if tag in ("ul", "ol"):
            return self._list(node)
        if tag == "table":
            return self._table(node)
        if tag == "pre":
            code = node.text(deep=True).strip("\n")
            return f"```\n{code}\n```" if code.strip() else ""
        if tag == "blockquote":
            inner = self.block(node)
            return "\n".join(f"> {line}" if line else ">" for line in inner.splitlines())
        if tag == "hr":
            return "---"
        if tag == "dt":
            return f"**{self._inline_children(node)}**"
        return self.block(node)

    def _list(self, node: LexborNode, depth: int = 0) -> str:
        lines: list[str] = []
        ordered = node.tag == "ol"
        items = [child for child in node.iter() if child.tag == "li"]
        for number, item in enumerate(items, 1):
            marker = f"{number}." if ordered else "-"
            text_parts, nested = [], []
            for child in item.iter(include_text=True):
                if child.tag in ("ul", "ol"):
                    nested.append(self._list(child, depth + 1))
                elif child.tag in _BLOCKS:
                    text_parts.append(" " + self._inline_children(child) + " ")
                elif child.tag not in _DROP:
                    text_parts.append(self.inline(child))
            text = _SPACES.sub(" ", "".join(text_parts)).strip()
            lines.append(f"{'  ' * depth}{marker} {text}".rstrip())
            lines.extend(nested)
        return "\n".join(lines)

    def _table(self, node: LexborNode) -> str:
        rows = [[self._cell(cell) for cell in row.iter() if cell.tag in ("td", "th")] for row in node.css("tr")]
        rows = [row for row in rows if row]
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        header, *body = rows
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
        lines += ["| " + " | ".join(row) + " |" for row in body]
        return "\n".join(lines)

    def _cell(self, node: LexborNode) -> str:
        return self._inline_children(node).replace("|", "\\|")

    # --- inline: text with emphasis, links, images

    def _inline_children(self, node: LexborNode) -> str:
        parts = [self.inline(child) for child in node.iter(include_text=True) if child.tag not in _DROP]
        return _SPACES.sub(" ", "".join(parts)).strip()

    def inline(self, node: LexborNode) -> str:
        tag = node.tag
        if tag == "-text":
            return node.text_content or ""
        if tag == "br":
            return " "
        if tag == "img":
            src = node.attributes.get("src")
            alt = (node.attributes.get("alt") or "").strip()
            return f"![{alt}]({urljoin(self.url, src)})" if src else ""
        text = self._inline_children(node)
        if not text:
            return ""
        if tag == "a":
            href = (node.attributes.get("href") or "").strip()
            if href and not href.startswith(("#", "javascript:")):
                return f"[{text}]({urljoin(self.url, href)})"
            return text
        if tag in ("strong", "b"):
            return f"**{text}**"
        if tag in ("em", "i"):
            return f"_{text}_"
        if tag == "code":
            return f"`{text}`"
        if tag in _BLOCKS:  # a block inside inline content (a div in a link…): keep it on the line
            return f" {text} "
        return text
