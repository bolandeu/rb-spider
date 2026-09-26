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
    onpage: dict = field(default_factory=dict)  # title/description/h1/h2 details, see _onpage()

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

    if 300 <= status_code < 400:
        location = headers.get("location")
        page.redirect_url = _absolute(url, location) if location else None
        return page
    if not body or "html" not in (content_type or "text/html"):
        return page

    tree = LexborHTMLParser(body)
    title = tree.css_first("title")
    page.title = _text(title) if title else None
    page.onpage = _onpage(tree)
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
