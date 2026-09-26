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
from crawlee import ConcurrencySettings
from crawlee.configuration import Configuration
from crawlee.crawlers import HttpCrawler, HttpCrawlingContext
from crawlee.events import LocalEventManager
from crawlee.http_clients import ImpitHttpClient
from crawlee.storage_clients import MemoryStorageClient
from crawlee.storages import RequestQueue

from . import storage
from .errors import InvalidArguments
from .extract import normalize_url, parse_page

PROGRESS_EVERY_S = 5.0

# Crawlee warns that passing our own Configuration sets it globally as a side effect — intended
# here (one crawl per process), so the warning is noise for the user.
logging.getLogger("crawlee._service_locator").setLevel(logging.ERROR)


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
    max_urls: int | None,
    concurrency: int,
    on_progress: Callable[[int], None] | None,
) -> None:
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
        configure_logging=False,
    )
    host = urlsplit(start_url).netloc
    seen = {start_url}
    last_progress = time.monotonic()

    @crawler.router.default_handler
    async def handle(ctx: HttpCrawlingContext) -> None:
        nonlocal last_progress
        response = ctx.http_response
        page = parse_page(ctx.request.url, response.status_code, dict(response.headers), await response.read())
        writer.add(page, depth=ctx.request.crawl_depth)

        targets = [*page.links, page.redirect_url] if page.redirect_url else page.links
        new = [u for u in dict.fromkeys(targets) if urlsplit(u).netloc == host and u not in seen]
        if max_urls is not None:  # exact bound: Crawlee's own limit is overshot by requests already in flight
            new = new[: max(0, max_urls - len(seen))]
        if new:
            seen.update(new)
            await ctx.add_requests(new)

        if on_progress and time.monotonic() - last_progress >= PROGRESS_EVERY_S:
            last_progress = time.monotonic()
            on_progress(writer.count)

    try:
        await crawler.run([start_url])
    finally:
        await queue.drop()


def crawl_site(
    engine: sa.Engine,
    start_url: str,
    project: str,
    *,
    max_urls: int | None = None,
    concurrency: int = 20,
    on_progress: Callable[[int], None] | None = None,
) -> CrawlResult:
    """Crawl `start_url`'s host breadth-first and store every response under a new crawl."""
    start_url = _validate_start_url(start_url)
    crawl_id = storage.start_crawl(engine, project, start_url)
    writer = storage.PageWriter(engine, crawl_id)
    started = time.monotonic()
    status = "failed"
    try:
        asyncio.run(_run(start_url, writer, max_urls, concurrency, on_progress))
        status = "finished"
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    finally:
        writer.flush()
        pages = storage.finish_crawl(engine, crawl_id, status)
    return CrawlResult(crawl_id, project, start_url, status, pages, round(time.monotonic() - started, 1))
