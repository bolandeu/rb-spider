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
    page.title = title.text(strip=True) if title else None
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
