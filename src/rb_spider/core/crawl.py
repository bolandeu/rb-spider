"""Crawl a site with Crawlee and store every response in the crawl database.

Crawlee only fetches (queue, concurrency, HTTP); `extract.parse_page` reads the response and
`storage.PageWriter` persists it in batches. Choices below come from the performance prototype
(issue #3, docs/spec.md section 2):
- redirects are not followed by the HTTP client — every hop is a page of its own for SEO;
- the queue is in memory, and URLs already seen are dropped before reaching it (the durable,
  resumable queue is issue #14);
- 3xx/4xx/5xx are data, not errors, so Crawlee must not retry or fail on them.

robots.txt is checked here, not by Crawlee: Crawlee always reads it as `*`, while a crawl as
Googlebot must obey the Googlebot group (and `robots = "report"` needs the verdict without
skipping the URL). Crawl-delay becomes a request-rate cap — one site per crawl, so a per-domain
throttling queue isn't needed.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

import sqlalchemy as sa
from crawlee import ConcurrencySettings, Request
from crawlee._utils.robots import RobotsTxtFile
from crawlee.configuration import Configuration
from crawlee.crawlers import HttpCrawler, HttpCrawlingContext
from crawlee.events import LocalEventManager
from crawlee.http_clients import HttpClient, ImpitHttpClient
from crawlee.proxy_configuration import ProxyConfiguration
from crawlee.storage_clients import MemoryStorageClient
from crawlee.storages import RequestQueue

from ..credentials import manager as credentials
from . import issues, storage
from .errors import AuthRequired, InvalidArguments
from .extract import Page, normalize_url, parse_page
from .settings import CrawlSettings, Settings

PROGRESS_EVERY_S = 5.0
PROXY_CREDENTIAL = "proxy"

# Crawlee warns that passing our own Configuration sets it globally as a side effect — intended
# here (one crawl per process), so the warning is noise for the user.
logging.getLogger("crawlee._service_locator").setLevel(logging.ERROR)
# A URL that never answers is data (issue internal_no_response, the error text is stored), not a
# crash: without this Crawlee prints a full traceback per such URL.
logging.getLogger("HttpCrawler").addFilter(
    lambda record: not any(noise in record.getMessage() for noise in ("reached maximum retries", "Retrying request"))
)
# An unreachable robots.txt means "no rules" (search engines treat it so, and so does RobotsGate) —
# routine for other sites' links, not something to warn about per host.
logging.getLogger("crawlee._utils.robots").setLevel(logging.ERROR)


@dataclass
class CrawlResult:
    crawl_id: int
    project: str
    start_url: str
    status: str
    pages: int
    elapsed_s: float


def _validate_start_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise InvalidArguments(f"Start URL must be an absolute http(s) URL, got '{url}'.")
    return normalize_url(url)


def project_for(url: str) -> str:
    """Default project name for a crawl started outside a spider project: the site's host."""
    return urlsplit(url).netloc


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

    def internal(self, url: str) -> bool:
        """Part of the site (the start host, or any subdomain with `all_subdomains`)."""
        parts = urlsplit(url)
        if self.all_subdomains:
            hostname = parts.hostname or ""
            return hostname == self.domain or hostname.endswith(f".{self.domain}")
        return parts.netloc == self.host

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


class RobotsGate:
    """robots.txt verdicts for the crawl's user agent, one robots.txt per host, fetched once."""

    def __init__(self, http_client: HttpClient, user_agent: str) -> None:
        self.http_client, self.user_agent = http_client, user_agent
        self._files: dict[str, RobotsTxtFile | None] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _file(self, url: str) -> RobotsTxtFile | None:
        host = urlsplit(url).netloc
        async with self._locks.setdefault(host, asyncio.Lock()):
            if host not in self._files:
                try:
                    self._files[host] = await RobotsTxtFile.find(url, self.http_client)
                except Exception:  # unreachable robots.txt: crawl as if there were none, like search bots do
                    self._files[host] = None
            return self._files[host]

    async def allowed(self, url: str) -> bool:
        robots = await self._file(url)
        return robots is None or robots.is_allowed(url, self.user_agent)

    async def crawl_delay(self, url: str) -> int | None:
        robots = await self._file(url)
        return robots.get_crawl_delay(self.user_agent) if robots else None


def proxy_urls(settings: CrawlSettings) -> list[str]:
    """`crawl.proxy_urls` with `{password}` filled from the keychain (`spider auth login --provider proxy`)."""
    if not any("{password}" in url for url in settings.proxy_urls):
        return list(settings.proxy_urls)
    password = credentials.get_secret(PROXY_CREDENTIAL)
    if password is None:
        raise AuthRequired(PROXY_CREDENTIAL)
    return [url.replace("{password}", password) for url in settings.proxy_urls]


def requests_per_minute(settings: CrawlSettings, crawl_delay: int | None) -> float:
    """The request-rate cap: `max_rps` and robots.txt Crawl-delay, whichever is stricter; inf — none."""
    caps = [float("inf")]
    if settings.max_rps:
        caps.append(settings.max_rps * 60)
    if crawl_delay:
        caps.append(60 / crawl_delay)
    return min(caps)


async def _run(
    start_url: str,
    writer: storage.PageWriter,
    all_settings: Settings,
    on_progress: Callable[[int], None] | None,
) -> None:
    settings, collect = all_settings.crawl, all_settings.collect
    user_agent = settings.resolved_user_agent
    headers = {**settings.headers, **({"User-Agent": user_agent} if user_agent else {})}
    scope = Scope(start_url, settings)
    proxies = proxy_urls(settings)
    http_client = ImpitHttpClient(follow_redirects=False)
    robots = RobotsGate(http_client, settings.robots_user_agent or user_agent or "*")
    crawl_delay = await robots.crawl_delay(start_url) if settings.robots == "respect" else None

    config = Configuration(log_level="WARNING")
    storage_client = MemoryStorageClient()
    # A queue of its own per crawl: Crawlee caches the default queue per process, so a second
    # crawl in the same process (library use, tests) would see every URL as already handled.
    queue = await RequestQueue.open(
        alias=f"crawl-{writer.crawl_id}", storage_client=storage_client, configuration=config
    )
    concurrency = settings.concurrency
    crawler = HttpCrawler(
        http_client=http_client,
        storage_client=storage_client,
        request_manager=queue,
        configuration=config,
        event_manager=LocalEventManager(),
        concurrency_settings=ConcurrencySettings(
            min_concurrency=max(1, concurrency // 2),
            desired_concurrency=concurrency,
            max_concurrency=concurrency,
            max_tasks_per_minute=requests_per_minute(settings, crawl_delay),
        ),
        max_requests_per_crawl=settings.max_urls,
        max_request_retries=1,
        navigation_timeout=timedelta(seconds=settings.timeout_s),
        request_handler_timeout=timedelta(seconds=settings.timeout_s + 60),
        ignore_http_error_status_codes=list(range(300, 600)),
        respect_robots_txt_file=False,  # RobotsGate, see the module docstring
        configure_logging=False,
        **({"proxy_configuration": ProxyConfiguration(proxy_urls=list(proxies))} if proxies else {}),
    )
    depth_of: dict[str, int] = {}  # every URL handed to the queue; its depth is known before it's fetched
    reported_blocked: set[str] = set()  # robots = "report": fetched anyway, flagged as disallowed
    last_progress = time.monotonic()

    def progress() -> None:
        nonlocal last_progress
        if on_progress and time.monotonic() - last_progress >= PROGRESS_EVERY_S:
            last_progress = time.monotonic()
            on_progress(writer.count)

    async def admit(urls: list[str], depth: int, *, start: bool = False, resources: bool = False) -> list[Request]:
        """URLs that pass scope, limits and robots.txt, as requests; disallowed ones go to the report.

        The start URL is always crawled — it's what the user asked for. URLs to check (other sites,
        outside the start folder, and every resource: images, CSS, JS…) carry `user_data["check"]`:
        status and size only. robots.txt applies to all of them — a disallowed resource is what
        Screaming Frog calls a Blocked Resource.
        """
        if settings.max_depth is not None and depth > settings.max_depth:
            return []

        def role(url: str) -> str | None:
            if start:
                return "crawl"
            found = scope.role(url)
            return "check" if resources and found else found

        roles = {u: role(u) for u in dict.fromkeys(urls) if u not in depth_of}
        new = [u for u, role in roles.items() if role]
        if settings.max_urls is not None:  # exact bound: Crawlee's own limit is overshot by requests in flight
            new = new[: max(0, settings.max_urls - len(depth_of))]
        admitted = []
        for url in new:
            depth_of[url] = depth
            check = roles[url] == "check"
            if settings.robots != "ignore" and not await robots.allowed(url):
                if settings.robots == "respect":  # never fetched, but part of the report
                    writer.add(Page.blocked_by_robots(url), depth=depth)
                    continue
                reported_blocked.add(url)
            admitted.append(Request.from_url(url, headers=headers or None, user_data={"check": check}))
        return admitted

    def resources_to_check(page: Page) -> tuple[list[str], list[dict]]:
        """Resources to check (status, size) and their link rows — collect.images / css / js / media / iframes."""
        check: list[str] = []
        rows: list[dict] = []
        options = {"image": collect.images, "css": collect.css, "js": collect.js, "media": collect.media,
                   "iframe": collect.iframes}  # fmt: skip
        for resource in page.resources:
            option = options[resource.kind]
            if option.store:
                rows.append({"source": page.url, "target": resource.url, "kind": resource.kind,
                             "internal": scope.internal(resource.url), "alt": resource.alt,
                             "alt_attr": resource.alt_attr, "sized": resource.sized})  # fmt: skip
            if option.follow:
                check.append(resource.url)
        return check, rows

    def links_to_follow(page: Page) -> tuple[list[str], list[dict]]:
        """What to enqueue from a crawled page, and the link rows to keep (collect.* decides both)."""
        follow: list[str] = []
        rows: list[dict] = []
        counts = {"internal_outlinks": 0, "external_outlinks": 0, "internal_nofollow_outlinks": 0}
        for link in page.links:
            internal = scope.internal(link.url)
            kind = collect.internal_links if internal else collect.external_links
            if not link.nofollow:
                counts["internal_outlinks" if internal else "external_outlinks"] += 1
            elif internal:
                counts["internal_nofollow_outlinks"] += 1
            if kind.store:
                rows.append({"source": page.url, "target": link.url, "kind": "hyperlink", "internal": internal,
                             "anchor": link.anchor, "alt": link.alt, "rel": link.rel, "nofollow": link.nofollow})  # fmt: skip
            nofollow_ok = settings.follow_internal_nofollow if internal else settings.follow_external_nofollow
            if kind.follow and (not link.nofollow or nofollow_ok):
                follow.append(link.url)
        page.onpage |= counts
        if settings.max_links_per_page is not None:
            follow = follow[: settings.max_links_per_page]

        extra = [  # (target, kind, collect option): redirects are always followed and kept with the site's links
            (page.redirect_url, "redirect", collect.internal_links),
            (page.refresh_url, "refresh", collect.meta_refresh),
            (page.onpage.get("canonical_url"), "canonical", collect.canonicals),
        ]
        for target, kind, option in extra:
            if not target or target == page.url:
                continue
            if option.store or kind == "redirect":
                rows.append({"source": page.url, "target": target, "kind": kind, "internal": scope.internal(target)})
            if option.follow or kind == "redirect":
                follow.append(target)
        return follow, rows

    @crawler.router.default_handler
    async def handle(ctx: HttpCrawlingContext) -> None:
        response = ctx.http_response
        body = await response.read()
        check = bool(ctx.request.user_data.get("check"))
        page = parse_page(
            ctx.request.url,
            response.status_code,
            dict(response.headers),
            b"" if check else body,  # a checked URL is not read: status, headers, redirect target only
            content_exclude=settings.content_exclude,
            srcset=collect.images_srcset,
        )
        page.bytes = len(body)
        page.onpage |= {"external": not scope.internal(page.url), "parsed": not check}
        if page.url in reported_blocked:
            page.blocked = "robots_txt"
        depth = depth_of.get(page.url, ctx.request.crawl_depth)
        if check:
            writer.add(page, depth=depth)
            progress()
            return

        follow, rows = links_to_follow(page)
        check, resource_rows = resources_to_check(page)
        writer.add(page, depth=depth, body=body)
        writer.add_links(rows + resource_rows)
        requests = await admit(follow, depth + 1) + await admit(check, depth + 1, resources=True)
        if requests:
            await ctx.add_requests(requests)
        progress()

    @crawler.failed_request_handler
    async def failed(ctx, error: Exception) -> None:
        # No usable response even after the retry: timeout, refused/reset connection, bad TLS...
        url = ctx.request.url
        page = Page.no_response(url, f"{type(error).__name__}: {error}"[:500])
        page.onpage = {"external": not scope.internal(url), "parsed": False}
        writer.add(page, depth=depth_of.get(url, 0))
        progress()

    try:
        start_requests = await admit([start_url], 0, start=True)
        if start_requests:
            await crawler.run(start_requests)
    finally:
        await queue.drop()


def crawl_site(
    engine: sa.Engine,
    start_url: str,
    project: str,
    settings: Settings | None = None,
    *,
    on_progress: Callable[[int], None] | None = None,
) -> CrawlResult:
    """Crawl `start_url`'s site breadth-first, store every response under a new crawl, run the checks.

    The resolved settings are kept with the crawl (`spider crawls show`).
    """
    settings = settings or Settings()
    start_url = _validate_start_url(start_url)
    proxy_urls(settings.crawl)  # a missing proxy password fails before a crawl is registered
    crawl_id = storage.start_crawl(engine, project, start_url, settings.model_dump(mode="json"))
    writer = storage.PageWriter(engine, crawl_id, store_html=settings.crawl.store_html)
    started = time.monotonic()
    status = "failed"
    try:
        asyncio.run(_run(start_url, writer, settings, on_progress))
        status = "finished"
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    finally:
        writer.flush()
        if writer.html_engine is not None:
            writer.html_engine.dispose()
        pages = storage.finish_crawl(engine, crawl_id, status)
        issues.analyze(engine, crawl_id, settings.thresholds)  # an interrupted crawl is still worth a report
    return CrawlResult(crawl_id, project, start_url, status, pages, round(time.monotonic() - started, 1))
