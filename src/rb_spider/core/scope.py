"""What a crawl takes from one fetched page: which URLs are the site's, what to follow, which links to keep.

Kept apart from `crawl` because it runs in the parser worker processes (`crawl.Parser`): it imports
neither Crawlee nor SQLAlchemy nor pydantic, so the workers stay small, and everything here pickles
as plain data. Settings are read once, in the constructors, in the crawl's own process.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from .extract import Page, parse_page

if TYPE_CHECKING:
    from .settings import CollectSettings, CrawlSettings

# Columns of a `links` row as `PageReader` builds it (the crawl id is added by the writer).
LINK_FIELDS = ("source", "target", "kind", "internal", "anchor", "alt", "rel", "nofollow", "alt_attr", "sized")


class Scope:
    """Which URLs belong to the crawl: the site (host or subdomains), the start folder, include/exclude, length."""

    def __init__(self, start_url: str, settings: CrawlSettings) -> None:
        start = urlsplit(start_url)
        self.host = start.netloc
        self.domain = start.hostname.removeprefix("www.") if start.hostname else self.host
        self.all_subdomains = settings.all_subdomains
        self.folder = start.path[: start.path.rfind("/") + 1] if settings.stay_in_start_folder else ""
        self.include = [re.compile(p) for p in settings.include]
        self.exclude = [re.compile(p) for p in settings.exclude]
        self.max_url_length = settings.max_url_length
        self.check_outside_folder = settings.check_outside_start_folder
        self.check_external = True  # narrowed by collect.external_links.follow at the link level
        # URLs reaching here are normalized (path at least "/"), so the site's own start with one of these
        self._own_prefixes = (f"http://{self.host}/", f"https://{self.host}/")

    def internal(self, url: str) -> bool:
        """Part of the site (the start host, or any subdomain with `all_subdomains`)."""
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
        if self.folder and not urlsplit(url).path.startswith(self.folder):
            return "check" if self.check_outside_folder else None
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

    def __init__(self, scope: Scope, crawl: CrawlSettings, collect: CollectSettings) -> None:
        self.scope = scope
        self.content_exclude: Sequence[str] = list(crawl.content_exclude)
        self.srcset = collect.images_srcset
        self.follow_internal_nofollow = crawl.follow_internal_nofollow
        self.follow_external_nofollow = crawl.follow_external_nofollow
        self.max_links_per_page = crawl.max_links_per_page
        kinds = {"internal_links": collect.internal_links, "external_links": collect.external_links,
                 "canonical": collect.canonicals, "refresh": collect.meta_refresh, "image": collect.images,
                 "css": collect.css, "js": collect.js, "media": collect.media, "iframe": collect.iframes}  # fmt: skip
        self.kinds = {name: _Kind(option.follow, option.store) for name, option in kinds.items()}

    def read(self, url: str, status_code: int, headers: dict[str, str], body: bytes, *, check: bool) -> Reading:
        """A checked URL (`check`) is not read: status, headers and redirect target only."""
        page = parse_page(url, status_code, headers, b"" if check else body,
                          content_exclude=self.content_exclude, srcset=self.srcset)  # fmt: skip
        page.bytes = len(body)
        page.onpage |= {"external": not self.scope.internal(page.url), "parsed": not check}
        if check:
            return Reading(page, [], [], [])
        follow, rows = self._links_to_follow(page)
        to_check, resource_rows = self._resources_to_check(page)
        page.links, page.resources = [], []  # consumed: don't carry them back to the crawl process
        return Reading(page, follow, to_check, rows + resource_rows)

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
                             link.nofollow, None, None))  # fmt: skip
            nofollow_ok = self.follow_internal_nofollow if internal else self.follow_external_nofollow
            if kind.follow and (not link.nofollow or nofollow_ok):
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
                rows.append((page.url, target, kind, internal_of(target), None, None, None, False, None, None))
            if option.follow or kind == "redirect":
                follow.append(target)
        return follow, rows

    def _resources_to_check(self, page: Page) -> tuple[list[str], list[tuple]]:
        """Resources to check (status, size) and their link rows — collect.images / css / js / media / iframes."""
        check: list[str] = []
        rows: list[tuple] = []
        for resource in page.resources:
            option = self.kinds[resource.kind]
            if option.store:
                rows.append((page.url, resource.url, resource.kind, self.scope.internal(resource.url), None,
                             resource.alt, None, False, resource.alt_attr, resource.sized))  # fmt: skip
            if option.follow:
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
