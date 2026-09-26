"""SEO data from one HTTP response — a pure function, independent of the crawl engine.

The same code handles raw HTML and (later) browser-rendered HTML, so it takes plain values,
never a Crawlee context.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from selectolax.lexbor import LexborHTMLParser

from . import content

_FOLLOWABLE_SCHEMES = {"http", "https"}
# `<meta http-equiv="refresh">` content and the `Refresh` header share a format: "5; url=/next".
_REFRESH_URL = re.compile(r"""^\s*\d*(?:\.\d+)?\s*[;,]\s*url\s*=\s*['"]?([^'"]+)""", re.IGNORECASE)


@dataclass
class Link:
    url: str  # absolute http(s), fragment stripped
    anchor: str = ""  # link text, whitespace collapsed
    alt: str | None = None  # alt of an image inside the link (image links)
    rel: str | None = None  # raw rel attribute, lower-case
    nofollow: bool = False
    fragment: str | None = None  # the #bookmark the link jumps to, when it names one (see bookmark_fragment)


@dataclass
class Resource:
    """Something the page loads rather than links to: image, stylesheet, script, media, iframe."""

    url: str
    kind: str  # image | css | js | media | iframe
    alt: str | None = None  # images
    alt_attr: bool | None = None  # images: the alt attribute exists
    sized: bool | None = None  # images: width and height attributes are both set


@dataclass
class Page:
    url: str
    status_code: int
    content_type: str | None
    bytes: int
    redirect_url: str | None = None
    title: str | None = None
    links: list[Link] = field(default_factory=list)  # <a href> to http(s) URLs, in page order
    resources: list[Resource] = field(default_factory=list)
    refresh_url: str | None = None  # client-side redirect target (meta / HTTP Refresh)
    refresh_kind: str | None = None  # "meta" | "http"
    error: str | None = None  # no response: why (status_code is 0)
    blocked: str | None = None  # not fetched on purpose: "robots_txt" (status_code is 0)
    hreflang: list[tuple[str, str]] = field(default_factory=list)  # (code as written, absolute URL): HTML + Link
    pagination: list[tuple[str, str]] = field(default_factory=list)  # ("next" | "prev", absolute URL): HTML + Link
    forms: list[str] = field(default_factory=list)  # each <form>'s action, absolute (no action: the page itself)
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


_REL_PARAM = re.compile(r'rel\s*=\s*"?([^";,]*)"?', re.IGNORECASE)


def _header_links(headers: dict[str, str], rel: str) -> list[tuple[str, str]]:
    """`Link: <url>; rel="alternate"; hreflang="en"` entries whose rel (a space-separated list) has `rel`."""
    found = []
    for target, params in _LINK_HEADER.findall(headers.get("link", "")):
        value = _REL_PARAM.search(params)
        if value and rel in value.group(1).lower().split():
            found.append((target.strip(), params))
    return found


def _header_canonicals(headers: dict[str, str]) -> list[str]:
    """Targets of `Link: <url>; rel="canonical"` (the header can list several links)."""
    return [target for target, _ in _header_links(headers, "canonical")]


_HREFLANG_PARAM = re.compile(r'hreflang\s*=\s*"?([^";,\s]+)"?', re.IGNORECASE)


def _hreflang(url: str, headers: dict[str, str], tree: LexborHTMLParser | None) -> tuple[list[tuple[str, str]], int]:
    """Hreflang annotations — <link rel="alternate" hreflang> and the Link header — and how many sit outside <head>."""
    found: list[tuple[str, str]] = []
    for target, params in _header_links(headers, "alternate"):
        if (code := _HREFLANG_PARAM.search(params)) and (absolute := _absolute(url, target)):
            found.append((code.group(1).strip(), absolute))
    outside = 0
    if tree is not None:
        head_ids = {n.mem_id for n in tree.head.css("link")} if tree.head else set()
        for link in tree.css("link[hreflang]"):
            if "alternate" not in (link.attributes.get("rel") or "").lower().split():
                continue
            absolute = _absolute(url, link.attributes.get("href") or "")
            code = (link.attributes.get("hreflang") or "").strip()
            if absolute and code:
                found.append((code, absolute))
                outside += link.mem_id not in head_ids
    return found, outside


_PAGINATION_RELS = {"next": "next", "prev": "prev", "previous": "prev"}


def _pagination(url: str, headers: dict[str, str], tree: LexborHTMLParser | None) -> list[tuple[str, str]]:
    """rel="next" / "prev" of <link> elements and the Link header, in page order: ("next" | "prev", URL)."""
    found: list[tuple[str, str]] = []
    for rel in ("next", "prev", "previous"):
        for target, _ in _header_links(headers, rel):
            if absolute := _absolute(url, target):
                found.append((_PAGINATION_RELS[rel], absolute))
    if tree is not None:
        for link in tree.css("link[rel]"):
            rels = [
                _PAGINATION_RELS[r] for r in (link.attributes.get("rel") or "").lower().split() if r in _PAGINATION_RELS
            ]
            absolute = _absolute(url, link.attributes.get("href") or "")
            if rels and absolute:
                found.append((rels[0], absolute))
    return found


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


_LOREM = re.compile(r"lorem\s+ipsum", re.IGNORECASE)


DEFAULT_CONTENT_EXCLUDE = ("nav", "footer")


def _content(tree: LexborHTMLParser, body: bytes, exclude: Sequence[str], minhash: bool) -> dict:
    """Exact-duplicate hash, the page's own text (menus and footers aside) and measures of it. Mutates `tree`: call it last."""
    tree.strip_tags(["script", "style", "noscript", "template"])
    for selector in exclude:
        for node in tree.css(selector):
            node.decompose()
    text = tree.body.text(separator=" ") if tree.body else ""
    tokens = text.split()
    readable = content.readability(text)
    return {
        "content_md5": hashlib.md5(body).hexdigest(),  # noqa: S324 — a fingerprint, not security
        "word_count": len(tokens),
        "lorem_ipsum": bool(_LOREM.search(text)),
        "flesch": readable[0] if readable else None,
        "words_per_sentence": readable[1] if readable else None,
        # visible text (single spaces between words), % of the HTML
        "text_ratio": round(100 * (sum(map(len, tokens)) + len(tokens)) / len(body), 1) if body else None,
        "minhash": content.signature(text) if minhash else None,
    }


def visible_text(body: bytes) -> str:
    """The page's text as a reader sees it: no scripts, styles or templates, whitespace collapsed."""
    tree = LexborHTMLParser(body)
    tree.strip_tags(["script", "style", "noscript", "template"])
    root = tree.body or tree.root
    return _WHITESPACE.sub(" ", root.text(separator=" ")).strip() if root else ""


# Fragments that aren't bookmarks: "#top" scrolls up without an id (HTML spec), "#!" / "#/" are
# client-side routes, "#:~:text=" is a text fragment.
_NOT_BOOKMARK = re.compile(r"^(top|!|/|:~:)", re.IGNORECASE)


def bookmark_fragment(href: str) -> str | None:
    """The id a link's `#fragment` points at (percent-decoded), or None when it isn't a bookmark."""
    _, sep, fragment = href.partition("#")
    fragment = unquote(fragment.strip())
    return fragment if sep and fragment and not _NOT_BOOKMARK.match(fragment) else None


def anchor_hash(name: str) -> bytes:
    """A 2-byte fingerprint of a bookmark target: a page keeps these instead of its ids (see anchor_ids)."""
    return hashlib.blake2b(name.encode(), digest_size=2).digest()


def anchor_ids(tree: LexborHTMLParser) -> str:
    """What `#fragment` links can land on — every id and <a name> — as sorted 2-byte fingerprints, base64.

    A page may have hundreds of ids; fingerprints keep that ~3 bytes each, with a ~1-in-20000 chance per id
    that a missing bookmark passes for a present one. "" — the page has none.
    """
    names = {node.attributes.get("id") or "" for node in tree.css("[id]")}
    names |= {node.attributes.get("name") or "" for node in tree.css("a[name]")}
    fingerprints = sorted({anchor_hash(name) for name in names if name})
    return base64.b64encode(b"".join(fingerprints)).decode()


def _links(url: str, tree: LexborHTMLParser) -> list[Link]:
    links = []
    for anchor in tree.css("a[href]"):
        href = anchor.attributes.get("href") or ""
        target = _absolute(url, href)
        if target is None:
            continue
        rel = (anchor.attributes.get("rel") or "").lower() or None
        image = anchor.css_first("img")
        links.append(
            Link(
                url=target,
                anchor=_text(anchor),
                alt=(image.attributes.get("alt") or "").strip() if image else None,
                rel=rel,
                nofollow="nofollow" in (rel or "").split(),
                fragment=bookmark_fragment(href),
            )
        )
    return links


def _srcset_urls(value: str) -> list[str]:
    """`a.jpg 1x, b.jpg 480w` -> ["a.jpg", "b.jpg"]."""
    return [part.strip().split()[0] for part in value.split(",") if part.strip()]


def _resources(url: str, tree: LexborHTMLParser, srcset: bool) -> list[Resource]:
    found: list[Resource] = []

    def add(href: str | None, kind: str, **extra) -> None:
        target = _absolute(url, href or "") if href else None
        if target:
            found.append(Resource(target, kind, **extra))

    for img in tree.css("img"):
        attrs = img.attributes
        image = {"alt": (attrs.get("alt") or "").strip() if "alt" in attrs else None, "alt_attr": "alt" in attrs,
                 "sized": bool(attrs.get("width")) and bool(attrs.get("height"))}  # fmt: skip
        add(attrs.get("src"), "image", **image)
        if srcset and attrs.get("srcset"):
            for candidate in _srcset_urls(attrs.get("srcset") or ""):
                add(candidate, "image", **image)
    for link in tree.css("link[rel]"):
        if "stylesheet" in (link.attributes.get("rel") or "").lower().split():
            add(link.attributes.get("href"), "css")
    for script in tree.css("script[src]"):
        add(script.attributes.get("src"), "js")
    for media in tree.css("video[src], audio[src], video source[src], audio source[src]"):
        add(media.attributes.get("src"), "media")
    for iframe in tree.css("iframe[src]"):
        add(iframe.attributes.get("src"), "iframe")
    return found


# --- security (#29)
_SECURE_REFERRER = {"no-referrer", "no-referrer-when-downgrade", "strict-origin", "strict-origin-when-cross-origin"}


def missing_security_headers(headers: dict[str, str]) -> str | None:
    """Security headers a response lacks (or sets to a weak value), as ",hsts,csp,xcto,xfo,referrer,".

    Header names must be lower-case. HSTS is listed whatever the scheme; the rule looks at HTTPS pages only.
    """
    referrer = [t.strip().lower() for t in headers.get("referrer-policy", "").split(",") if t.strip()]
    checks = {
        "hsts": not headers.get("strict-transport-security", "").strip(),
        "csp": not headers.get("content-security-policy", "").strip(),
        "xcto": headers.get("x-content-type-options", "").strip().lower() != "nosniff",
        "xfo": headers.get("x-frame-options", "").strip().upper() not in ("DENY", "SAMEORIGIN"),
        "referrer": not referrer or referrer[-1] not in _SECURE_REFERRER,  # the last known policy wins
    }
    missing = [name for name, failed in checks.items() if failed]
    return f",{','.join(missing)}," if missing else None


_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image"), (b"\xff\xd8\xff", "image"), (b"GIF8", "image"), (b"%PDF-", "pdf"),
)  # fmt: skip
_HTML_START = re.compile(rb"^\s*(<!--.*?-->\s*)*<(!doctype\s+html|html|head|body)\b", re.IGNORECASE | re.DOTALL)


def _declared_kind(content_type: str | None) -> str | None:
    value = (content_type or "").split(";")[0].strip().lower()
    if not value:
        return None
    if "html" in value:
        return "html"
    if value.startswith("image/"):
        return "image"
    return "pdf" if value == "application/pdf" else "other"


def sniffed_mismatch(content_type: str | None, body: bytes) -> str | None:
    """What the body really is ("html", "image", "pdf") when its first bytes say otherwise than Content-Type.

    Only unmistakable signatures count — image and PDF magic bytes, an HTML document start — so a JSON or
    text body is never "wrong"; None — they agree, or the body can't be told.
    """
    head = body[:1024].removeprefix(b"\xef\xbb\xbf")
    sniffed = next((kind for magic, kind in _MAGIC if head.startswith(magic)), None)
    if sniffed is None and (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        sniffed = "image"
    if sniffed is None and _HTML_START.match(head):
        sniffed = "html"
    declared = _declared_kind(content_type)
    if sniffed is None or declared is None or declared == sniffed:
        return None
    return f"{declared} → {sniffed}"


def _forms(url: str, tree: LexborHTMLParser) -> list[str]:
    actions = []
    for form in tree.css("form"):
        action = (form.attributes.get("action") or "").strip()
        if target := (_absolute(url, action) if action else normalize_url(url)):
            actions.append(target)
    return actions


def _unsafe_blank_links(url: str, tree: LexborHTMLParser) -> int:
    """<a target="_blank"> to another origin without rel="noopener" / "noreferrer"."""
    origin = urlsplit(url)[:2]
    count = 0
    for anchor in tree.css("a[target]"):
        if (anchor.attributes.get("target") or "").strip().lower() != "_blank":
            continue
        target = _absolute(url, anchor.attributes.get("href") or "")
        rel = (anchor.attributes.get("rel") or "").lower().split()
        count += bool(target) and urlsplit(target)[:2] != origin and not {"noopener", "noreferrer"} & set(rel)
    return count


def _protocol_relative_resources(tree: LexborHTMLParser) -> int:
    """Resources loaded as `//host/path`: they follow the page's scheme, HTTP on an HTTP page."""
    values = [img.attributes.get("src") for img in tree.css("img[src]")]
    values += [n.attributes.get("href") for n in tree.css("link[rel]")
               if "stylesheet" in (n.attributes.get("rel") or "").lower().split()]  # fmt: skip
    values += [
        n.attributes.get("src") for n in tree.css("script[src], video[src], audio[src], source[src], iframe[src]")
    ]
    return sum((value or "").strip().startswith("//") for value in values)


_JS_NAVIGATION = re.compile(r"location|window\.open", re.IGNORECASE)


def _uncrawlable_links(tree: LexborHTMLParser) -> int:
    """Link-like elements a crawler can't follow: `javascript:` hrefs, href on non-links, onclick navigation."""
    count = 0
    for node in tree.css("[href]"):
        href = (node.attributes.get("href") or "").strip().lower()
        if node.tag == "a":
            count += href.startswith("javascript:")
        elif node.tag not in ("link", "base", "area"):
            count += 1
    for node in tree.css("[onclick]"):
        count += bool(_JS_NAVIGATION.search(node.attributes.get("onclick") or ""))
    return count


def parse_page(
    url: str,
    status_code: int,
    headers: dict[str, str],
    body: bytes,
    *,
    content_exclude: Sequence[str] = DEFAULT_CONTENT_EXCLUDE,
    srcset: bool = False,
    minhash: bool = False,
) -> Page:
    """Extract what a crawl needs from a response: redirect targets, title, outgoing links."""
    headers = {k.lower(): v for k, v in headers.items()}
    content_type = headers.get("content-type")
    page = Page(url=url, status_code=status_code, content_type=content_type, bytes=len(body))
    if refresh := _refresh_target(url, headers.get("refresh")):
        page.refresh_url, page.refresh_kind = refresh, "http"
    is_html = bool(body) and "html" in (content_type or "text/html") and not 300 <= status_code < 400
    tree = LexborHTMLParser(body) if is_html else None
    page.onpage = _directives_and_canonical(url, headers, tree)
    page.hreflang, page.onpage["hreflang_outside_head"] = _hreflang(url, headers, tree)
    page.pagination = _pagination(url, headers, tree)
    rels = {rel for rel, _ in page.pagination}
    page.onpage["pagination"] = "paginated" if "prev" in rels else "first" if rels else None

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
    page.links = _links(url, tree)
    page.resources = _resources(url, tree, srcset)
    page.onpage["uncrawlable_outlinks"] = _uncrawlable_links(tree)
    page.onpage["anchor_ids"] = anchor_ids(tree)
    page.forms = _forms(url, tree)
    page.onpage |= {"forms": len(page.forms), "unsafe_blank_links": _unsafe_blank_links(url, tree),
                    "protocol_relative": _protocol_relative_resources(tree)}  # fmt: skip
    page.onpage |= _content(tree, body, content_exclude, minhash)
    return page
