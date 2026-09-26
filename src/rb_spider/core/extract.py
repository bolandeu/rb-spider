"""SEO data from one HTTP response — a pure function, independent of the crawl engine.

The same code handles raw HTML and (later) browser-rendered HTML, so it takes plain values,
never a Crawlee context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

from selectolax.lexbor import LexborHTMLParser

_FOLLOWABLE_SCHEMES = {"http", "https"}
# `<meta http-equiv="refresh">` content and the `Refresh` header share a format: "5; url=/next".
_REFRESH_URL = re.compile(r"""^\s*\d*(?:\.\d+)?\s*[;,]\s*url\s*=\s*['"]?([^'"]+)""", re.IGNORECASE)


@dataclass
class Page:
    url: str
    status_code: int
    content_type: str | None
    bytes: int
    redirect_url: str | None = None
    title: str | None = None
    links: list[str] = field(default_factory=list)  # absolute http(s) URLs, fragments stripped, in page order
    refresh_url: str | None = None  # client-side redirect target (meta / HTTP Refresh)
    refresh_kind: str | None = None  # "meta" | "http"
    error: str | None = None  # no response: why (status_code is 0)
    blocked: str | None = None  # not fetched on purpose: "robots_txt" (status_code is 0)
    onpage: dict = field(default_factory=dict)  # extra `pages` columns: _onpage(), _directives_and_canonical()

    @classmethod
    def no_response(cls, url: str, error: str) -> Page:
        return cls(url=url, status_code=0, content_type=None, bytes=0, error=error)

    @classmethod
    def blocked_by_robots(cls, url: str) -> Page:
        return cls(url=url, status_code=0, content_type=None, bytes=0, blocked="robots_txt")


def normalize_url(url: str) -> str:
    """Drop the #fragment: it never changes what the server returns."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def _absolute(base: str, href: str) -> str | None:
    url = urljoin(base, href.strip())
    return normalize_url(url) if urlsplit(url).scheme in _FOLLOWABLE_SCHEMES else None


def _refresh_target(base: str, value: str | None) -> str | None:
    match = _REFRESH_URL.match(value or "")
    return _absolute(base, match.group(1)) if match else None


_WHITESPACE = re.compile(r"\s+")

# Directive names Screaming Frog reports on (Directives tab); anything else is kept but unnamed.
DIRECTIVES = {
    "index", "noindex", "follow", "nofollow", "none", "noarchive", "nosnippet", "noimageindex",
    "notranslate", "noodp", "noydir", "unavailable_after", "all", "max-snippet", "max-image-preview",
    "max-video-preview", "indexifembedded",
}  # fmt: skip
_CANONICAL_BAD_ATTRS = ("hreflang", "lang", "media", "type")
_LINK_HEADER = re.compile(r"<([^>]*)>\s*;([^,]*)")


def _directive_tokens(value: str) -> list[str]:
    """`noindex, nofollow` / `googlebot: noindex` / `unavailable_after: 2030-01-01` -> directive names."""
    tokens = []
    for raw in value.lower().split(","):
        token = raw.strip()
        head, sep, rest = token.partition(":")
        if sep and head.strip() not in DIRECTIVES:  # "botname: directive" — keep the directive
            token = rest.strip()
        name = token.split(":", 1)[0].strip()
        if name:
            tokens.append(name)
    return tokens


def _header_canonicals(headers: dict[str, str]) -> list[str]:
    """Targets of `Link: <url>; rel="canonical"` (the header can list several links)."""
    return [
        target.strip()
        for target, params in _LINK_HEADER.findall(headers.get("link", ""))
        if re.search(r'rel\s*=\s*"?canonical"?', params, re.IGNORECASE)
    ]


def _directives_and_canonical(url: str, headers: dict[str, str], tree: LexborHTMLParser | None) -> dict:
    """Directives and canonical from HTTP headers and (for HTML) the page, in `pages` column names."""
    tokens = _directive_tokens(headers.get("x-robots-tag", ""))
    raw_canonicals = [(href, False) for href in _header_canonicals(headers)]  # (href, from HTML)
    robots_outside = canonical_outside = 0
    invalid_attr = False
    if tree is not None:
        head_ids = {n.mem_id for n in tree.head.css("meta, link")} if tree.head else set()
        for meta in tree.css("meta[name]"):
            if (meta.attributes.get("name") or "").lower() == "robots":
                tokens += _directive_tokens(meta.attributes.get("content") or "")
                robots_outside += meta.mem_id not in head_ids
        for link in tree.css("link[rel]"):
            if "canonical" in (link.attributes.get("rel") or "").lower().split():
                raw_canonicals.append(((link.attributes.get("href") or "").strip(), True))
                canonical_outside += link.mem_id not in head_ids
                invalid_attr |= any(attr in link.attributes for attr in _CANONICAL_BAD_ATTRS)
    targets = [urljoin(url, href) for href, _ in raw_canonicals if href]
    distinct = {normalize_url(t) for t in targets}
    return {
        "robots_directives": f",{','.join(dict.fromkeys(tokens))}," if tokens else None,
        "robots_outside_head": robots_outside,
        "canonical_url": normalize_url(targets[0]) if targets else None,
        "canonical_count": len(raw_canonicals),
        "canonical_conflict": len(distinct) > 1,
        "canonical_outside_head": canonical_outside,
        "canonical_invalid_attr": invalid_attr,
        "canonical_relative": any(href and not urlsplit(href).scheme for href, _ in raw_canonicals),
        "canonical_fragment": any("#" in href for href, _ in raw_canonicals),
    }


def _text(node) -> str:
    return _WHITESPACE.sub(" ", node.text(separator=" ")).strip()


def _onpage(tree: LexborHTMLParser) -> dict:
    """What the Page Titles / Meta Description / H1 / H2 checks need, in `pages` column names."""
    head = tree.head
    titles = tree.css("title")
    descriptions = [m for m in tree.css("meta[name]") if (m.attributes.get("name") or "").lower() == "description"]
    in_head = {n.mem_id for n in head.css("title, meta")} if head else set()  # mem_id: stable node identity
    headings = tree.css("h1, h2, h3, h4, h5, h6")
    h1s = [h for h in headings if h.tag == "h1"]
    h2s = [h for h in headings if h.tag == "h2"]

    h1_text, h1_from_alt = None, False
    if h1s:
        h1_text = _text(h1s[0])
        alts = [img.attributes.get("alt") or "" for img in h1s[0].css("img")]
        if any(a.strip() for a in alts):
            h1_from_alt = True
            h1_text = " ".join(filter(None, [h1_text, *(a.strip() for a in alts)])).strip()
    h2_sequential = None
    if h2s:
        first_h2 = next(i for i, h in enumerate(headings) if h.tag == "h2")
        h2_sequential = first_h2 > 0 and headings[first_h2 - 1].tag == "h1"
    return {
        "title_count": len(titles),
        "title_outside_head": sum(t.mem_id not in in_head for t in titles),
        "meta_description": (descriptions[0].attributes.get("content") or "").strip() if descriptions else None,
        "meta_description_count": len(descriptions),
        "meta_description_outside_head": sum(m.mem_id not in in_head for m in descriptions),
        "h1": h1_text,
        "h1_count": len(h1s),
        "h1_from_alt": h1_from_alt,
        "h1_first_heading": bool(headings) and headings[0].tag == "h1" if h1s else None,
        "h2": _text(h2s[0]) if h2s else None,
        "h2_count": len(h2s),
        "h2_sequential": h2_sequential,
    }


def parse_page(url: str, status_code: int, headers: dict[str, str], body: bytes) -> Page:
    """Extract what a crawl needs from a response: redirect targets, title, outgoing links."""
    headers = {k.lower(): v for k, v in headers.items()}
    content_type = headers.get("content-type")
    page = Page(url=url, status_code=status_code, content_type=content_type, bytes=len(body))
    if refresh := _refresh_target(url, headers.get("refresh")):
        page.refresh_url, page.refresh_kind = refresh, "http"
    is_html = bool(body) and "html" in (content_type or "text/html") and not 300 <= status_code < 400
    tree = LexborHTMLParser(body) if is_html else None
    page.onpage = _directives_and_canonical(url, headers, tree)

    if 300 <= status_code < 400:
        location = headers.get("location")
        page.redirect_url = _absolute(url, location) if location else None
        return page
    if tree is None:
        return page

    title = tree.css_first("title")
    page.title = _text(title) if title else None
    page.onpage |= _onpage(tree)
    if page.refresh_url is None:
        for meta in tree.css("meta[http-equiv]"):
            if (meta.attributes.get("http-equiv") or "").lower() == "refresh":
                if refresh := _refresh_target(url, meta.attributes.get("content")):
                    page.refresh_url, page.refresh_kind = refresh, "meta"
                break
    for anchor in tree.css("a[href]"):
        link = _absolute(url, anchor.attributes.get("href") or "")
        if link:
            page.links.append(link)
    return page
