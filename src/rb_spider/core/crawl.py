"""Crawl a site with Crawlee and store every response in the crawl database.

Crawlee only fetches (queue, concurrency, HTTP); `extract.parse_page` reads the response and
`storage.PageWriter` persists it in batches. Choices below come from the performance prototype
(issue #3, docs/spec.md section 2):
- redirects are not followed by the HTTP client — every hop is a page of its own for SEO;
- the queue is in memory, and URLs already seen are dropped before reaching it (the durable,
  resumable queue is issue #14);
- 3xx/4xx/5xx are data, not errors, so Crawlee must not retry or fail on them.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

import sqlalchemy as sa
from crawlee import ConcurrencySettings, Request
from crawlee.configuration import Configuration
from crawlee.crawlers import HttpCrawler, HttpCrawlingContext
from crawlee.events import LocalEventManager
from crawlee.http_clients import ImpitHttpClient
from crawlee.storage_clients import MemoryStorageClient
from crawlee.storages import RequestQueue

from . import issues, storage
from .errors import InvalidArguments
from .extract import Page, normalize_url, parse_page
from .settings import CrawlSettings, Settings

PROGRESS_EVERY_S = 5.0

# Crawlee warns that passing our own Configuration sets it globally as a side effect — intended
# here (one crawl per process), so the warning is noise for the user.
logging.getLogger("crawlee._service_locator").setLevel(logging.ERROR)
# Crawl-delay from robots.txt isn't honoured yet (needs Crawlee's ThrottlingRequestManager) —
# tracked in issue #7 (politeness settings); until then the per-crawl warning is noise.
logging.getLogger("HttpCrawler").addFilter(lambda record: "Crawl-delay" not in record.getMessage())
# A URL that never answers is data (issue internal_no_response, the error text is stored), not a
# crash: without this Crawlee prints a full traceback per such URL.
logging.getLogger("HttpCrawler").addFilter(lambda record: "reached maximum retries" not in record.getMessage())


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


async def _run(
    start_url: str,
    writer: storage.PageWriter,
    settings: CrawlSettings,
    on_progress: Callable[[int], None] | None,
) -> None:
    max_urls, concurrency = settings.max_urls, settings.concurrency
    headers = {"User-Agent": settings.user_agent} if settings.user_agent else None

    def request(url: str) -> Request:
        return Request.from_url(url, headers=headers)

    config = Configuration(log_level="WARNING")
    storage_client = MemoryStorageClient()
    # A queue of its own per crawl: Crawlee caches the default queue per process, so a second
    # crawl in the same process (library use, tests) would see every URL as already handled.
    queue = await RequestQueue.open(
        alias=f"crawl-{writer.crawl_id}", storage_client=storage_client, configuration=config
    )
    crawler = HttpCrawler(
        http_client=ImpitHttpClient(follow_redirects=False),
        storage_client=storage_client,
        request_manager=queue,
        configuration=config,
        event_manager=LocalEventManager(),
        concurrency_settings=ConcurrencySettings(
            min_concurrency=max(1, concurrency // 2), desired_concurrency=concurrency, max_concurrency=concurrency
        ),
        max_requests_per_crawl=max_urls,
        max_request_retries=1,
        request_handler_timeout=timedelta(seconds=60),
        ignore_http_error_status_codes=list(range(300, 600)),
        respect_robots_txt_file=settings.respect_robots,
        configure_logging=False,
    )
    host = urlsplit(start_url).netloc
    depth_of = {start_url: 0}  # every URL handed to the queue; its depth is known before it's fetched
    last_progress = time.monotonic()

    def progress() -> None:
        nonlocal last_progress
        if on_progress and time.monotonic() - last_progress >= PROGRESS_EVERY_S:
            last_progress = time.monotonic()
            on_progress(writer.count)

    @crawler.router.default_handler
    async def handle(ctx: HttpCrawlingContext) -> None:
        response = ctx.http_response
        page = parse_page(ctx.request.url, response.status_code, dict(response.headers), await response.read())
        depth = depth_of.get(page.url, ctx.request.crawl_depth)
        writer.add(page, depth=depth)

        targets = [*page.links, page.redirect_url, page.refresh_url]
        new = [u for u in dict.fromkeys(targets) if u and urlsplit(u).netloc == host and u not in depth_of]
        if max_urls is not None:  # exact bound: Crawlee's own limit is overshot by requests already in flight
            new = new[: max(0, max_urls - len(depth_of))]
        if new:
            depth_of.update(dict.fromkeys(new, depth + 1))
            await ctx.add_requests([request(u) for u in new])
        progress()

    @crawler.failed_request_handler
    async def failed(ctx, error: Exception) -> None:
        # No usable response even after the retry: timeout, refused/reset connection, bad TLS...
        url = ctx.request.url
        writer.add(Page.no_response(url, f"{type(error).__name__}: {error}"[:500]), depth=depth_of.get(url, 0))
        progress()

    @crawler.on_skipped_request
    async def skipped(url: str, reason: str) -> None:
        # Disallowed by robots.txt: never fetched, but part of the report (what a search bot can't reach).
        writer.add(Page.blocked_by_robots(url), depth=depth_of.get(url, 0))

    try:
        await crawler.run([request(start_url)])
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
    """Crawl `start_url`'s host breadth-first, store every response under a new crawl, run the checks.

    The resolved settings are kept with the crawl (`spider crawls show`).
    """
    settings = settings or Settings()
    start_url = _validate_start_url(start_url)
    crawl_id = storage.start_crawl(engine, project, start_url, settings.model_dump(mode="json"))
    writer = storage.PageWriter(engine, crawl_id)
    started = time.monotonic()
    status = "failed"
    try:
        asyncio.run(_run(start_url, writer, settings.crawl, on_progress))
        status = "finished"
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    finally:
        writer.flush()
        pages = storage.finish_crawl(engine, crawl_id, status)
        issues.analyze(engine, crawl_id, settings.thresholds)  # an interrupted crawl is still worth a report
    return CrawlResult(crawl_id, project, start_url, status, pages, round(time.monotonic() - started, 1))
