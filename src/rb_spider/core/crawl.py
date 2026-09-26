"""Crawl a site with Crawlee and store every response in the crawl database.

Crawlee only fetches (queue, concurrency, HTTP); `scope.PageReader` reads the response and
`storage.PageWriter` persists it in batches. Choices below come from the performance prototype
(issue #3, docs/spec.md section 2):
- redirects are not followed by the HTTP client — every hop is a page of its own for SEO;
- the queue is in memory (`queue.MemoryQueue`), URLs already seen are dropped before reaching it,
  and the `frontier` table mirrors it for resuming;
- 3xx/4xx/5xx are data, not errors, so Crawlee must not retry or fail on them.

robots.txt is checked here, not by Crawlee: Crawlee always reads it as `*`, while a crawl as
Googlebot must obey the Googlebot group (and `robots = "report"` needs the verdict without
skipping the URL). Crawl-delay becomes a request-rate cap — one site per crawl, so a per-domain
throttling queue isn't needed.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import importlib.util
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from importlib.machinery import ModuleSpec
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa
from crawlee import ConcurrencySettings, Request
from crawlee._utils.robots import RobotsTxtFile
from crawlee.configuration import Configuration
from crawlee.crawlers import HttpCrawler, HttpCrawlingContext
from crawlee.events import LocalEventManager
from crawlee.http_clients import HttpClient, ImpitHttpClient
from crawlee.proxy_configuration import ProxyConfiguration
from crawlee.storage_clients import MemoryStorageClient

from ..credentials import manager as credentials
from . import issues, render, storage
from .errors import (
    AuthRequired,
    HttpClientUnavailable,
    InvalidArguments,
    NearDuplicatesUnavailable,
    StructuredDataUnavailable,
)
from .extract import Page, normalize_url
from .queue import MemoryQueue
from .render import Renderer
from .scope import PageReader, Reading, Scope, init_worker, read_in_worker
from .settings import CrawlSettings, Settings

PROGRESS_EVERY_S = 5.0
# Parsing is half the CPU of a crawl; past this many pages it moves to worker processes. Small crawls
# (and tests) stay in one process: spawning workers costs more than it saves there.
PARSE_POOL_AFTER = 200
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


class Parser:
    """Reads fetched pages (`scope.PageReader`), in worker processes once the crawl is big enough.

    The event loop, HTTP and database writes share one core; parsing HTML and sorting its links is
    most of a crawl's CPU, and offloading it is what lets a crawl go past ~600 URL/s. Workers
    (`crawl.parse_workers`) start lazily, on the first page past `PARSE_POOL_AFTER`.
    """

    def __init__(self, reader: PageReader, workers: int | None) -> None:
        self.reader = reader
        self.workers = min(4, max(0, (os.cpu_count() or 1) - 1)) if workers is None else workers
        self.pool: ProcessPoolExecutor | None = None
        self.parsed = 0

    async def read(self, url: str, status_code: int, headers: dict[str, str], body: bytes, *, check: bool) -> Reading:
        self.parsed += 1
        if check or not body or not self.workers or self.parsed <= PARSE_POOL_AFTER:
            return self.reader.read(url, status_code, headers, body, check=check)
        if self.pool is None:
            self._hide_main()
            self.pool = ProcessPoolExecutor(self.workers, initializer=init_worker, initargs=(self.reader,))
        call = functools.partial(read_in_worker, url, status_code, headers, body)
        return await asyncio.get_running_loop().run_in_executor(self.pool, call)

    def _hide_main(self) -> None:
        """Keep workers light: a spawned worker re-runs the main module, and the `spider` entry script
        imports the whole CLI (~40 MB more per worker). multiprocessing skips a main module whose spec
        is named `*.__main__` — so for the pool's lifetime the entry script gets one."""
        self._main = sys.modules["__main__"]
        self._main_spec = getattr(self._main, "__spec__", None)
        if self._main_spec is None:
            self._main.__spec__ = ModuleSpec("rb_spider.__main__", None)

    def close(self) -> None:
        if self.pool is not None:
            self.pool.shutdown(cancel_futures=True)
            self._main.__spec__ = self._main_spec


def proxy_urls(settings: CrawlSettings) -> list[str]:
    """`crawl.proxy_urls` with `{password}` filled from the keychain (`spider auth login --provider proxy`)."""
    if not any("{password}" in url for url in settings.proxy_urls):
        return list(settings.proxy_urls)
    password = credentials.get_secret(PROXY_CREDENTIAL)
    if password is None:
        raise AuthRequired(PROXY_CREDENTIAL)
    return [url.replace("{password}", password) for url in settings.proxy_urls]


def http_client(settings: CrawlSettings) -> HttpClient:
    """`crawl.http_client`, never following redirects itself: every step is a page of its own."""
    if settings.http_client == "curl":
        if importlib.util.find_spec("curl_cffi") is None:
            raise HttpClientUnavailable
        from crawlee.http_clients import CurlImpersonateHttpClient

        return CurlImpersonateHttpClient(allow_redirects=False, **({} if settings.verify_tls else {"verify": False}))
    return ImpitHttpClient(follow_redirects=False, verify=settings.verify_tls)


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
    resume: storage.Frontier | None = None,
) -> None:
    settings, collect = all_settings.crawl, all_settings.collect
    user_agent = settings.resolved_user_agent
    headers = {**settings.headers, **({"User-Agent": user_agent} if user_agent else {})}
    # list mode: the site is whatever the list is on; the listed URLs are the frontier's depth-0 entries
    listed = settings.mode == "list"
    hosts = {urlsplit(url).netloc for url, depth in resume.seen.items() if depth == 0} if listed and resume else None
    scope = Scope(start_url, settings, hosts)
    proxies = proxy_urls(settings)
    client = http_client(settings)
    robots = RobotsGate(client, settings.robots_user_agent or user_agent or "*")
    crawl_delay = await robots.crawl_delay(start_url) if settings.robots == "respect" else None

    config = Configuration(log_level="WARNING")
    storage_client = MemoryStorageClient()

    def request(url: str, check: bool) -> Request:
        return Request.from_url(url, headers=headers or None, user_data={"check": check})

    queue = MemoryQueue(request)
    concurrency = settings.concurrency
    renderer = (
        Renderer(tabs=settings.render_tabs, wait_ms=settings.render_wait_ms, timeout_s=settings.timeout_s,
                 user_agent=user_agent, headers=settings.headers, browser=settings.render_browser)
        if settings.render == "always" else None
    )  # fmt: skip
    # a handler may first wait for a free browser tab: every tab busy with pages ahead of it
    render_wait_s = (settings.timeout_s + settings.render_wait_ms / 1000) * -(-concurrency // settings.render_tabs)
    crawler = HttpCrawler(
        http_client=client,
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
        request_handler_timeout=timedelta(seconds=settings.timeout_s + 60 + (render_wait_s if renderer else 0)),
        ignore_http_error_status_codes=list(range(300, 600)),
        respect_robots_txt_file=False,  # RobotsGate, see the module docstring
        configure_logging=False,
        **({"proxy_configuration": ProxyConfiguration(proxy_urls=list(proxies))} if proxies else {}),
    )
    # every URL handed to the queue (mirrored in the `frontier` table); its depth is known before it's fetched
    depth_of: dict[str, int] = dict(resume.seen) if resume else {}
    parser = Parser(PageReader(scope, settings, collect, all_settings.rewrite), settings.parse_workers)
    response_ms: dict[str, int] = {}  # answered requests -> response time, until their handler stores it
    redirect_hops: dict[str, int] = {}  # redirect targets -> steps of the chain that led to them (max_redirects)
    # Response time around the client's own request: Crawlee's navigation hooks cost ~15% of a big crawl.
    client_crawl = client.crawl

    async def timed_crawl(request, *args, **kwargs):
        sent = time.monotonic()
        result = await client_crawl(request, *args, **kwargs)
        response_ms[request.url] = round((time.monotonic() - sent) * 1000)
        return result

    client.crawl = timed_crawl  # ty: ignore[invalid-assignment]
    last_progress = time.monotonic()
    hsts_hosts: set[str] = set()  # hosts that answered over HTTPS with Strict-Transport-Security (respect_hsts)

    def hsts_upgrade(url: str) -> str | None:
        """The https:// URL a browser would go to instead of this http:// one, under a known HSTS policy."""
        parts = urlsplit(url)
        if not settings.respect_hsts or parts.scheme != "http" or parts.hostname not in hsts_hosts:
            return None
        return urlunsplit(parts._replace(scheme="https"))

    def progress() -> None:
        nonlocal last_progress
        if on_progress and time.monotonic() - last_progress >= PROGRESS_EVERY_S:
            last_progress = time.monotonic()
            on_progress(writer.count)

    async def admit(urls: list[str], depth: int, *, start: bool = False, resources: bool = False) -> None:
        """Enqueue the URLs that pass scope, limits and robots.txt; disallowed ones go to the report.

        The start URL is always crawled — it's what the user asked for; so is, in list mode, every step of
        a listed URL's redirects (to whatever host they lead). URLs to check (other sites,
        outside the start folder, and every resource: images, CSS, JS…) carry `user_data["check"]`:
        status and size only. robots.txt applies to all of them — a disallowed resource is what
        Screaming Frog calls a Blocked Resource.
        """
        if settings.max_depth is not None and depth > settings.max_depth:
            return

        def role(url: str) -> str | None:
            if start:
                return "crawl"
            found = scope.role(url)
            return "check" if resources and found else found

        roles = {u: role(u) for u in dict.fromkeys(urls) if u not in depth_of}
        new = [u for u, role in roles.items() if role]
        if settings.max_urls is not None:  # exact bound: Crawlee's own limit is overshot by requests in flight
            new = new[: max(0, settings.max_urls - len(depth_of))]
        upgraded: list[str] = []
        for url in new:
            depth_of[url] = depth
            check = roles[url] == "check"
            writer.queued(url, depth, check)
            if secure := hsts_upgrade(url):  # not fetched: recorded as the browser's own 307 to HTTPS
                writer.add(_hsts_redirect(url, secure, scope), depth=depth)
                writer.add_links([(url, secure, "redirect", scope.internal(secure), *[None] * 3, False, *[None] * 4)])
                upgraded.append(secure)
                continue
            if settings.robots == "respect" and not await robots.allowed(url):
                writer.add(Page.blocked_by_robots(url), depth=depth)  # never fetched, but part of the report
                continue
            queue.push(url, check)
        if upgraded:
            await admit(upgraded, depth, resources=resources)

    @crawler.router.default_handler
    async def handle(ctx: HttpCrawlingContext) -> None:
        response = ctx.http_response
        body = await response.read()
        check = bool(ctx.request.user_data.get("check"))
        headers = dict(response.headers)
        if ctx.request.url.startswith("https://") and any(k.lower() == "strict-transport-security" for k in headers):
            hsts_hosts.add(urlsplit(ctx.request.url).hostname or "")
        source, rendered = body, None
        if renderer and not check and response.status_code == 200 and _is_html(headers):
            dom = await renderer.render(ctx.request.url)
            source, rendered = dom or body, dom is not None
        reading = await parser.read(ctx.request.url, response.status_code, headers, source, check=check)
        page = reading.page
        page.bytes = len(body)  # the response's size, not the rendered DOM's
        page.onpage["response_ms"] = response_ms.pop(ctx.request.url, None)
        if page.redirect_url and page.redirect_url != page.url:
            hops = redirect_hops.pop(page.url, 0) + 1
            if hops > settings.max_redirects:  # the chain is long enough: its next step is not fetched
                reading.follow = [url for url in reading.follow if url != page.redirect_url]
            elif page.redirect_url not in depth_of:
                redirect_hops[page.redirect_url] = hops
        if rendered is not None:
            page.onpage["rendered"] = rendered
        if settings.robots == "report" and not await robots.allowed(page.url):
            page.blocked = "robots_txt"  # fetched anyway, flagged as disallowed
        depth = depth_of.get(page.url, ctx.request.crawl_depth)
        writer.add(page, depth=depth, body=None if check else body)
        writer.add_links(reading.links)
        await admit(reading.follow, depth + 1, start=listed)
        await admit(reading.check, depth + 1, resources=True)
        progress()

    @crawler.failed_request_handler
    async def failed(ctx, error: Exception) -> None:
        # No usable response even after the retry: timeout, refused/reset connection, bad TLS...
        url = ctx.request.url
        response_ms.pop(url, None)
        redirect_hops.pop(url, None)
        page = Page.no_response(url, f"{type(error).__name__}: {error}"[:500])
        page.onpage = {"external": not scope.internal(url), "parsed": False}
        writer.add(page, depth=depth_of.get(url, 0))
        progress()

    try:
        if resume and resume.seen:  # continue (or a list crawl's first run): the queue is whatever isn't done
            for url, depth, check in resume.pending:
                if settings.robots == "respect" and not await robots.allowed(url):  # a listed URL wasn't checked yet
                    writer.add(Page.blocked_by_robots(url), depth=depth)
                    continue
                queue.push(url, check)
        else:
            await admit([start_url], 0, start=True)
        writer.flush()  # the start URL (and a robots verdict on it) is on disk before any fetching
        if not await queue.is_empty():
            async with renderer or contextlib.nullcontext():
                await crawler.run()
    finally:
        parser.close()
        await queue.drop()


def _hsts_redirect(url: str, secure: str, scope: Scope) -> Page:
    page = Page(url=url, status_code=307, content_type=None, bytes=0, redirect_url=secure,
                error="HSTS Policy: не скачивался — браузер сам переходит на HTTPS")  # fmt: skip
    page.onpage = {"external": not scope.internal(url), "parsed": False}
    return page


def _is_html(headers: dict[str, str]) -> bool:
    content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), "text/html")
    return "html" in content_type


def register_crawl(engine: sa.Engine, start_url: str, project: str, settings: Settings | None = None) -> int:
    """Record a new crawl with its settings; `run_crawl` does the work (now, or in a detached process)."""
    settings = settings or Settings()
    start_url = _validate_start_url(start_url)
    if settings.crawl.mode == "list":  # a profile in list mode with one URL: a list of one
        return register_list_crawl(engine, [start_url], project, settings)
    _ready(settings)
    return storage.start_crawl(engine, project, start_url, settings.model_dump(mode="json"))


def _ready(settings: Settings) -> None:
    """What a crawl needs, checked before it is registered: the proxy password, the browser for rendering."""
    proxy_urls(settings.crawl)
    http_client(settings.crawl)  # the curl client without its extra fails here, before a crawl is registered
    if settings.crawl.render == "always":
        render.ensure_available()
    if settings.collect.near_duplicates and importlib.util.find_spec("datasketch") is None:
        raise NearDuplicatesUnavailable
    if {"microdata", "rdfa"} & set(settings.collect.structured_data) and importlib.util.find_spec("extruct") is None:
        raise StructuredDataUnavailable


def read_url_list(text: str) -> list[str]:
    """URLs of a list file: one per line, blank lines and `#` comments skipped, duplicates dropped."""
    urls: dict[str, None] = {}
    bad: list[str] = []
    for number, line in enumerate(text.removeprefix("\ufeff").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            urls[_validate_start_url(line)] = None
        except InvalidArguments:
            bad.append(f"{number}: {line[:100]}")
    if bad:
        raise InvalidArguments(f"Not absolute http(s) URLs in the list (line: text): {'; '.join(bad[:5])}"
                               + (f" and {len(bad) - 5} more" if len(bad) > 5 else ""))  # fmt: skip
    if not urls:
        raise InvalidArguments("The URL list is empty.")
    return list(urls)


def register_list_crawl(engine: sa.Engine, urls: list[str], project: str, settings: Settings | None = None) -> int:
    """Record a list-mode crawl: the listed URLs go straight into its queue (depth 0).

    From then on it is an ordinary crawl — `run_crawl`, `--detach` and resume take the queue from the
    database. Its "start URL" is the first listed one.
    """
    settings = (settings or Settings()).model_copy(deep=True)
    settings.crawl.mode = "list"
    urls = [_validate_start_url(url) for url in urls]
    _ready(settings)
    crawl_id = storage.start_crawl(engine, project, urls[0], settings.model_dump(mode="json"))
    storage.enqueue(engine, crawl_id, urls)
    return crawl_id


def run_crawl(
    engine: sa.Engine,
    crawl_id: int,
    *,
    on_progress: Callable[[int], None] | None = None,
) -> CrawlResult:
    """Crawl (or continue crawling) a registered crawl with its own settings, then run the checks.

    Continuing picks up the `frontier` a previous run left — after Ctrl-C, a crash or kill -9.
    """
    row, snapshot = storage.get_crawl(engine, crawl_id)
    settings = Settings.model_validate(snapshot or {})
    resume = storage.load_frontier(engine, crawl_id)
    writer = storage.PageWriter(engine, crawl_id, store_html=settings.crawl.store_html)
    storage.set_pid(engine, crawl_id, os.getpid())
    started = time.monotonic()
    status = "failed"
    try:
        asyncio.run(_run(row.start_url, writer, settings, on_progress, resume))
        status = "finished"
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    finally:
        writer.close()
        pages = storage.finish_crawl(engine, crawl_id, status)
        issues.analyze(engine, crawl_id, settings.thresholds)  # an interrupted crawl is still worth a report
    return CrawlResult(crawl_id, row.project, row.start_url, status, pages, round(time.monotonic() - started, 1))


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
    crawl_id = register_crawl(engine, start_url, project, settings)
    return run_crawl(engine, crawl_id, on_progress=on_progress)


def process_alive(pid: int | None) -> bool | None:
    """Is the process running? None when it can't be told (no pid, or Windows, where os.kill would kill)."""
    if pid is None or os.name == "nt":
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def ensure_resumable(engine: sa.Engine, crawl_id: int) -> None:
    """A crawl can be continued unless it finished or its process is still at it."""
    row, _ = storage.get_crawl(engine, crawl_id)
    if row.status == "finished":
        raise InvalidArguments(f"Crawl #{crawl_id} has already finished — start a new one with `spider crawl`.")
    if row.status == "running" and process_alive(storage.crawl_pid(engine, crawl_id)):
        raise InvalidArguments(f"Crawl #{crawl_id} is still running — see `spider status {crawl_id}`.")


def detach(crawl_id: int) -> tuple[int, Path]:
    """Run a registered crawl in its own background process; returns its pid and log file."""
    log_path = storage.db_path().parent / "logs" / f"crawl-{crawl_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "rb_spider", "--quiet", "crawls", "resume", str(crawl_id)]
    detached: dict = (
        {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
        if os.name == "nt"
        else {"start_new_session": True}
    )
    with log_path.open("ab") as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **detached)  # noqa: S603 — fixed argv
    return process.pid, log_path
