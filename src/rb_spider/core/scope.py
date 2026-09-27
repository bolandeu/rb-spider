"""What a crawl takes from one fetched page: which URLs are the site's, what to follow, which links to keep.

Kept apart from `crawl` because it runs in the parser worker processes (`crawl.Parser`): it imports
neither Crawlee nor SQLAlchemy nor pydantic, so the workers stay small, and everything here pickles
as plain data. Settings are read once, in the constructors, in the crawl's own process.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from .extract import Page, missing_security_headers, normalize_url, parse_page, sniffed_mismatch

if TYPE_CHECKING:
    from .settings import CollectSettings, CrawlSettings, RewriteSettings

# Columns of a `links` row as `PageReader` builds it (the crawl id is added by the writer).
LINK_FIELDS = (
    "source", "target", "kind", "internal", "anchor", "alt", "rel", "nofollow", "alt_attr", "sized", "fragment",
    "hreflang",
)  # fmt: skip
_PERCENT = re.compile(r"%[0-9a-fA-F]{2}")


class Rewriter:
    """`rewrite.*`: discovered URLs changed before anything else sees them — parameters dropped, regex
    replacements, lower case, %-encoding case. In that order; the result loses its #fragment like any URL."""

    def __init__(self, settings: RewriteSettings | None) -> None:
        """None — rewrite nothing."""
        self.remove = set(settings.remove_params) if settings else set()
        self.regex = [(re.compile(pattern), repl) for pattern, repl in settings.regex] if settings else []
        self.lowercase = bool(settings and settings.lowercase)
        self.percent = settings.percent_encoding if settings else "keep"
        self.active = bool(self.remove or self.regex or self.lowercase or self.percent != "keep")

    def __call__(self, url: str) -> str:
        if not self.active:
            return url
        if self.remove:
            parts = urlsplit(url)
            kept = [p for p in parts.query.split("&") if p and p.partition("=")[0] not in self.remove]
            url = urlunsplit(parts._replace(query="&".join(kept)))
        for pattern, replacement in self.regex:
            url = pattern.sub(replacement, url)
        if self.lowercase:
            url = url.lower()
        if self.percent != "keep":
            recase = str.upper if self.percent == "upper" else str.lower
            url = _PERCENT.sub(lambda m: recase(m.group()), url)
        return normalize_url(url)


class Scope:
    """Which URLs belong to the crawl: the site (host or subdomains), the start folder, include/exclude, length."""

    def __init__(self, start_url: str, settings: CrawlSettings, hosts: set[str] | None = None) -> None:
        """`hosts` — the site is these hosts (list mode: the hosts of the listed URLs), not the start URL's."""
        start = urlsplit(start_url)
        self.hosts = hosts
        self.host = start.netloc
        self.domain = start.hostname.removeprefix("www.") if start.hostname else self.host
        self.all_subdomains = settings.all_subdomains
        self.folder = start.path[: start.path.rfind("/") + 1] if settings.stay_in_start_folder else ""
        self.include = [re.compile(p) for p in settings.include]
        self.exclude = [re.compile(p) for p in settings.exclude]
        self.max_url_length = settings.max_url_length
        self.check_outside_folder = settings.check_outside_start_folder
        self.check_external = True  # narrowed by collect.external_links.follow at the link level
        self.cdns = tuple(host.lower().strip(".") for host in settings.cdns)
        self.max_folder_depth = settings.max_folder_depth
        self.max_query_params = settings.max_query_params
        # URLs reaching here are normalized (path at least "/"), so the site's own start with one of these
        self._own_prefixes = (f"http://{self.host}/", f"https://{self.host}/")

    def internal(self, url: str) -> bool:
        """Part of the site (the start host, any subdomain with `all_subdomains`, a CDN from `cdns`)."""
        if self.cdns:
            hostname = urlsplit(url).hostname or ""
            if hostname in self.cdns or hostname.endswith(tuple(f".{cdn}" for cdn in self.cdns)):
                return True
        if self.hosts is not None:
            return urlsplit(url).netloc in self.hosts
        if self.all_subdomains:
            hostname = urlsplit(url).hostname or ""
            return hostname == self.domain or hostname.endswith(f".{self.domain}")
        return url.startswith(self._own_prefixes) or urlsplit(url).netloc == self.host

    def role(self, url: str) -> str | None:
        """ "crawl" — fetch and read it; "check" — fetch for the status code only; None — leave it alone.

        include/exclude and the length cap apply to every URL (as in Screaming Frog); other sites and,
        with `check_outside_start_folder`, the site outside the start folder are only checked.
        """
        if len(url) > self.max_url_length:
            return None
        if self.include and not any(p.search(url) for p in self.include):
            return None
        if any(p.search(url) for p in self.exclude):
            return None
        if not self.internal(url):
            return "check" if self.check_external else None
        parts = urlsplit(url)
        if self.folder and not parts.path.startswith(self.folder):
            return "check" if self.check_outside_folder else None
        if self.max_folder_depth is not None and parts.path.rstrip("/").count("/") > self.max_folder_depth:
            return None  # /a/b/c has three levels: the page itself counts as one
        if self.max_query_params is not None and parts.query and len(parts.query.split("&")) > self.max_query_params:
            return None
        return "crawl"

    def crawlable(self, url: str) -> bool:
        return self.role(url) == "crawl"


@dataclass
class Reading:
    """One page as the crawl needs it: its row, the URLs to enqueue, the link rows to keep."""

    page: Page  # links and resources already turned into `follow`, `check` and `links`
    follow: list[str]  # to crawl (still subject to scope and limits)
    check: list[str]  # resources to check: status and size
    links: list[tuple]  # `links` rows, LINK_FIELDS order


@dataclass(frozen=True)
class _Kind:
    follow: bool
    store: bool


class PageReader:
    """Parses a response and applies `collect.*`: what to follow and what to store, per kind of link."""

    def __init__(
        self, scope: Scope, crawl: CrawlSettings, collect: CollectSettings, rewrite: RewriteSettings | None = None
    ) -> None:
        self.scope = scope
        self.rewrite = Rewriter(rewrite)
        self.content_exclude: Sequence[str] = list(crawl.content_exclude)
        self.srcset = collect.images_srcset
        self.minhash = collect.near_duplicates
        self.structured_data = tuple(collect.structured_data)
        self.validate = collect.html_validation
        self.store_uncrawlable = collect.uncrawlable_links
        self.keep_fragments = crawl.keep_fragments
        self.invalid_links = crawl.crawl_invalid_links
        self.assume_html = crawl.assume_html
        self.list_canonicals = crawl.list_follow_canonicals
        self.follow_internal_nofollow = crawl.follow_internal_nofollow
        self.follow_external_nofollow = crawl.follow_external_nofollow
        self.max_links_per_page = crawl.max_links_per_page
        self.listed = crawl.mode == "list"  # only the listed URLs and their redirects: no links, no resources
        kinds = {"internal_links": collect.internal_links, "external_links": collect.external_links,
                 "canonical": collect.canonicals, "refresh": collect.meta_refresh, "image": collect.images,
                 "hreflang": collect.hreflang, "pagination": collect.pagination,
                 "mobile_alternate": collect.mobile_alternate, "css": collect.css, "js": collect.js, "media": collect.media, "iframe": collect.iframes}  # fmt: skip
        self.kinds = {name: _Kind(option.follow, option.store) for name, option in kinds.items()}

    def read(self, url: str, status_code: int, headers: dict[str, str], body: bytes, *, check: bool) -> Reading:
        """A checked URL (`check`) is not read: status, headers and redirect target only."""
        page = parse_page(url, status_code, headers, b"" if check else body,
                          content_exclude=self.content_exclude, srcset=self.srcset, minhash=self.minhash,
                          structured_data=self.structured_data, validate=self.validate,
                          keep_fragments=self.keep_fragments, invalid_links=self.invalid_links,
                          assume_html=self.assume_html)  # fmt: skip
        page.bytes = len(body)
        lower = {k.lower(): v for k, v in headers.items()}
        page.onpage |= {"external": not self.scope.internal(page.url), "parsed": not check,
                        "headers": json.dumps(lower, ensure_ascii=False), "last_modified": lower.get("last-modified"),
                        "security_missing": missing_security_headers(lower),
                        "sniffed_type": sniffed_mismatch(page.content_type, body) if status_code == 200 else None}  # fmt: skip
        if check:
            return Reading(page, [], [], [])
        if self.rewrite.active:
            self._rewrite(page)
        follow, rows = self._links_to_follow(page)
        to_check, resource_rows = self._resources_to_check(page)
        page.links, page.resources = [], []  # consumed: don't carry them back to the crawl process
        return Reading(page, follow, to_check, rows + resource_rows)

    def _rewrite(self, page: Page) -> None:
        """Every URL the page leads to, as `rewrite.*` has it: links, resources, redirect, refresh, canonical."""
        rewrite = self.rewrite
        for item in (*page.links, *page.resources):
            item.url = rewrite(item.url)
        page.hreflang = [(code, rewrite(target)) for code, target in page.hreflang]
        page.pagination = [(rel, rewrite(target)) for rel, target in page.pagination]
        page.forms = [rewrite(action) for action in page.forms]
        page.mobile_alternates = [rewrite(target) for target in page.mobile_alternates]
        page.redirect_url = rewrite(page.redirect_url) if page.redirect_url else None
        page.refresh_url = rewrite(page.refresh_url) if page.refresh_url else None
        if page.onpage.get("canonical_url"):
            page.onpage["canonical_url"] = rewrite(page.onpage["canonical_url"])

    def _links_to_follow(self, page: Page) -> tuple[list[str], list[tuple]]:
        """What to enqueue from a crawled page, and the link rows to keep (collect.* decides both)."""
        internal_of = self.scope.internal
        follow: list[str] = []
        rows: list[tuple] = []
        counts = {"internal_outlinks": 0, "external_outlinks": 0, "internal_nofollow_outlinks": 0}
        for link in page.links:
            internal = internal_of(link.url)
            kind = self.kinds["internal_links" if internal else "external_links"]
            if not link.nofollow:
                counts["internal_outlinks" if internal else "external_outlinks"] += 1
            elif internal:
                counts["internal_nofollow_outlinks"] += 1
            if kind.store:
                rows.append((page.url, link.url, "hyperlink", internal, link.anchor, link.alt, link.rel,
                             link.nofollow, None, None, link.fragment, None))  # fmt: skip
            nofollow_ok = self.follow_internal_nofollow if internal else self.follow_external_nofollow
            if kind.follow and (not link.nofollow or nofollow_ok) and not self.listed:
                follow.append(link.url)
        page.onpage |= counts
        if self.max_links_per_page is not None:
            follow = follow[: self.max_links_per_page]

        extra = [  # (target, kind, collect option): redirects are always followed and kept with the site's links
            (page.redirect_url, "redirect", self.kinds["internal_links"]),
            (page.refresh_url, "refresh", self.kinds["refresh"]),
            (page.onpage.get("canonical_url"), "canonical", self.kinds["canonical"]),
        ]
        for target, kind, option in extra:
            if not target or target == page.url:
                continue
            if option.store or kind == "redirect":
                rows.append(
                    (page.url, target, kind, internal_of(target), None, None, None, False, None, None, None, None)
                )
            always = (
                ("redirect", "refresh", *(("canonical",) if self.list_canonicals else ()))
                if self.listed
                else ("redirect",)
            )
            if kind in always or (option.follow and not self.listed):
                follow.append(target)
        hreflang = self.kinds["hreflang"]
        for code, target in page.hreflang:  # self-references too: Missing Self Reference needs them
            if hreflang.store:
                rows.append((page.url, target, "hreflang", internal_of(target), None, None, None, False, None, None,
                             None, code))  # fmt: skip
            if hreflang.follow and not self.listed and target != page.url:
                follow.append(target)
        pagination = self.kinds["pagination"]
        for rel, target in page.pagination:
            if pagination.store:
                rows.append((page.url, target, rel, internal_of(target), None, None, None, False, None, None,
                             None, None))  # fmt: skip
            if pagination.follow and not self.listed and target != page.url:
                follow.append(target)
        mobile = self.kinds["mobile_alternate"]
        for target in page.mobile_alternates:
            if mobile.store:
                rows.append((page.url, target, "mobile_alternate", internal_of(target), None, None, None, False, None,
                             None, None, None))  # fmt: skip
            if mobile.follow and not self.listed:
                follow.append(target)
        if self.store_uncrawlable:  # kept for `spider links`: what the "link" is, not a URL to fetch
            rows += [(page.url, target, "uncrawlable", True, text, None, None, False, None, None, None, None)
                     for target, text in page.uncrawlable]  # fmt: skip
        for action in page.forms:  # kept with the links of its kind, never fetched
            internal = internal_of(action)
            if self.kinds["internal_links" if internal else "external_links"].store:
                rows.append((page.url, action, "form", internal, None, None, None, False, None, None, None, None))
        page.hreflang, page.pagination, page.forms, page.mobile_alternates, page.uncrawlable = [], [], [], [], []
        return follow, rows

    def _resources_to_check(self, page: Page) -> tuple[list[str], list[tuple]]:
        """Resources to check (status, size) and their link rows — collect.images / css / js / media / iframes."""
        check: list[str] = []
        rows: list[tuple] = []
        for resource in page.resources:
            option = self.kinds[resource.kind]
            if option.store:
                rows.append((page.url, resource.url, resource.kind, self.scope.internal(resource.url), None,
                             resource.alt, None, False, resource.alt_attr, resource.sized, None, None))  # fmt: skip
            if option.follow and not self.listed:
                check.append(resource.url)
        return check, rows


_reader: PageReader | None = None  # a worker process's own copy, set by `init_worker`


def init_worker(reader: PageReader) -> None:
    global _reader  # one reader per worker process, handed over once at its start
    _reader = reader


def read_in_worker(url: str, status_code: int, headers: dict[str, str], body: bytes) -> Reading:
    if _reader is None:
        raise RuntimeError("init_worker was not called in this process")
    return _reader.read(url, status_code, headers, body, check=False)
