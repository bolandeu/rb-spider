"""Custom Search, Custom Extraction and link positions — the user's own rules, applied in the parser workers.

Rules come from `[custom]` (settings) as plain data and are compiled once per worker. A page yields rows
(kind, name, value, n) for `custom_values`: a search rule — the number of matches (a row only when there are
any), an extractor — each value found. XPath needs lxml (extra `rb-spider[xpath]`), imported only for it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

MAX_VALUE = 2000  # characters kept of one extracted value


@dataclass(frozen=True)
class SearchRule:
    name: str
    pattern: re.Pattern
    scope: str  # html | text | element
    selector: str | None


@dataclass(frozen=True)
class ExtractRule:
    name: str
    kind: str  # css | xpath | regex
    query: str
    output: str  # text | html | inner_html | attribute name
    limit: int
    pattern: re.Pattern | None


class CustomRules:
    """The compiled `[custom]` rules; picklable (regex patterns and strings) for the worker processes."""

    def __init__(self, search: Sequence[Any], extract: Sequence[Any]) -> None:
        self.search = [
            SearchRule(rule.name, re.compile(rule.query if rule.regex else re.escape(rule.query),
                                             0 if rule.case_sensitive else re.IGNORECASE),
                       rule.scope, rule.selector)
            for rule in search
        ]  # fmt: skip
        self.extract = [
            ExtractRule(rule.name, rule.kind, rule.query, rule.output, rule.limit,
                        re.compile(rule.query) if rule.kind == "regex" else None)
            for rule in extract
        ]  # fmt: skip
        self.active = bool(self.search or self.extract)

    def before_content(self, tree, body: bytes) -> list[tuple]:
        """Rules that read the untouched page (HTML source, elements): run before the text is extracted."""
        rows: list[tuple] = []
        html: str | None = None
        for rule in self.search:
            if rule.scope == "html":
                html = html if html is not None else body.decode("utf-8", "replace")
                n = len(rule.pattern.findall(html))
            elif rule.scope == "element":
                n = sum(len(rule.pattern.findall(node.text(separator=" "))) for node in tree.css(rule.selector or "*"))
            else:
                continue
            if n:
                rows.append(("search", rule.name, None, n))
        for rule in self.extract:
            values = _extract(rule, tree, body)
            rows += [("extract", rule.name, value[:MAX_VALUE], index) for index, value in enumerate(values)]
        return rows

    def after_content(self, text: str) -> list[tuple]:
        """Search rules over the page's own text (menus and footers aside, as `crawl.content_exclude` says)."""
        rows = []
        for rule in self.search:
            if rule.scope == "text" and (n := len(rule.pattern.findall(text))):
                rows.append(("search", rule.name, None, n))
        return rows


def _node_output(node, output: str) -> str | None:
    if output == "text":
        return " ".join(node.text(separator=" ").split())
    if output == "html":
        return node.html
    if output == "inner_html":
        return "".join(child.html or "" for child in node.iter(include_text=True))
    return node.attributes.get(output)


def _extract(rule: ExtractRule, tree, body: bytes) -> list[str]:
    if rule.kind == "css":
        values = [_node_output(node, rule.output) for node in tree.css(rule.query)]
    elif rule.kind == "regex":
        assert rule.pattern is not None  # noqa: S101 — built together with kind
        found = rule.pattern.findall(body.decode("utf-8", "replace"))
        values = [m if isinstance(m, str) else m[0] for m in found]
    else:
        values = _xpath(rule, body)
    return [v for v in values if v not in (None, "")][: rule.limit]


def _xpath(rule: ExtractRule, body: bytes) -> list[str]:
    from lxml import html as lxml_html  # extra `rb-spider[xpath]`

    result = lxml_html.fromstring(body.decode("utf-8", "replace")).xpath(rule.query)  # bytes: lxml would guess latin-1
    if not isinstance(result, list):  # count(), string()…: one value
        return [str(result)]
    values = []
    for item in result:
        if isinstance(item, str):
            values.append(str(item))
        elif rule.output == "text":
            values.append(" ".join(item.text_content().split()))
        elif rule.output in ("html", "inner_html"):
            from lxml import etree  # ty: ignore[unresolved-import] — a compiled module

            outer = etree.tostring(item, encoding="unicode", with_tail=False)
            values.append(outer if rule.output == "html" else outer[outer.find(">") + 1 : outer.rfind("<")])
        else:
            values.append(item.get(rule.output))
    return values


# --- link positions ------------------------------------------------------------------------------

_SEGMENT_TAGS = {"head", "nav", "header", "footer", "aside", "main", "article", "section"}
_WORDS = re.compile(r"[/.#\s_-]+")


class LinkPlacer:
    """Where a link sits (head, nav, header, footer, sidebar, content) from its ancestors.

    A link's path is `/tag.class.id/…` of the landmark elements above it (html structure tags, and any element
    whose class or id has a word of a rule); rules — (word, label) pairs, the first word the path has wins (whole
    words split at / . - _ and spaces: "head" is not "header"), None — "content", the usual case, stored empty
    (the `links` view shows it). Paths are cached by parent element, so a menu of fifty links costs one walk.
    """

    def __init__(self, rules: Sequence[tuple[str, str]], keep_path: bool) -> None:
        self.rules = [(needle.lower(), label) for needle, label in rules]
        self.words = {needle for needle, _ in self.rules}
        self.keep_path = keep_path

    def placer(self):
        """A per-page function: element -> (position, path or None)."""
        cache: dict[int, str] = {}

        def path_of(node) -> str:
            if node is None or node.tag in ("html", "-undef", "#document"):
                return ""
            key = node.mem_id
            if key in cache:
                return cache[key]
            attrs = node.attributes
            marks = f"{attrs.get('class') or ''} {attrs.get('id') or ''}".lower()
            landmark = node.tag in _SEGMENT_TAGS or bool(self.words & set(_WORDS.split(marks)))
            segment = f"/{node.tag}" + (f".{'.'.join(marks.split())}" if marks.strip() else "") if landmark else ""
            cache[key] = path = path_of(node.parent) + segment
            return path

        placed: dict[int, tuple[str | None, str | None]] = {}

        def place(anchor) -> tuple[str | None, str | None]:
            parent = anchor.parent
            key = parent.mem_id if parent is not None else 0
            if key not in placed:  # links of one list share the parent: one lookup for all of them
                path = path_of(parent)
                words = set(_WORDS.split(path))
                position = next((label for needle, label in self.rules if needle in words), None)  # None: content
                placed[key] = position, (path or "/") if self.keep_path else None
            return placed[key]

        return place
