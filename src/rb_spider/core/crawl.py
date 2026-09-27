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
import base64
import contextlib
import functools
import importlib.util
import logging
import os
import re
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
from crawlee.sessions import Session
from crawlee.storage_clients import MemoryStorageClient

from ..credentials import manager as credentials
from . import issues, render, sitemaps, storage
from .errors import (
    AuthRequired,
    HttpClientUnavailable,
    InvalidArguments,
    NearDuplicatesUnavailable,
    StructuredDataUnavailable,
    XPathUnavailable,
)
from .extract import Page, normalize_url
from .queue import MemoryQueue
from .render import Renderer
from .scope import PageReader, Reading, Scope, init_worker, link_row, read_in_worker
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
    """robots.txt verdicts for the crawl's user agent, one robots.txt per host, fetched once.

    `custom` — the text to use for the site's own host instead of its real robots.txt (crawl.robots_custom).
    """

    def __init__(self, http_client: HttpClient, user_agent: str, custom: str | None = None, site: str = "") -> None:
        self.http_client, self.user_agent = http_client, user_agent
        self.custom, self.site = custom, site
        self._files: dict[str, RobotsTxtFile | None] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _file(self, url: str) -> RobotsTxtFile | None:
        host = urlsplit(url).netloc
        async with self._locks.setdefault(host, asyncio.Lock()):
            if host not in self._files:
                try:
                    if self.custom is not None and host == self.site:
                        self._files[host] = await RobotsTxtFile.from_content(url, self.custom)
                    else:
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

    def rule(self, url: str) -> str | None:
        """The robots.txt line that decided a URL ("Disallow: /private/"), for a host already read; None if unknown.

        protego doesn't say which rule matched, so this walks its rule set the way its can_fetch does — private
        fields: on a protego change it gives up (None) rather than failing the crawl.
        """
        robots = self._files.get(urlsplit(url).netloc)
        if robots is None:
            return None
        try:
            from protego._ruleset import _quote_path

            rule_set = robots._robots._get_matching_rule_set(self.user_agent)
            quoted = _quote_path(url)
            for rule in rule_set._rules if rule_set else []:
                if rule.value.match(quoted):
                    return f"{rule.field.title()}: {rule.value._pattern}"
        except Exception:  # noqa: S110 — see the docstring
            pass
        return None


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
    """`crawl.http_client`, never following redirects itself: every step is a page of its own.

    Cookies: Crawlee keeps them per session (`cookies = session`) or not at all (`none`). A custom CA (`ca_bundle`)
    only the curl client can load; impit has no such option.
    """
    cookies = settings.cookies == "session"
    if settings.http_client == "curl":
        if importlib.util.find_spec("curl_cffi") is None:
            raise HttpClientUnavailable
        from crawlee.http_clients import CurlImpersonateHttpClient

        verify: bool | str = settings.ca_bundle or settings.verify_tls
        return CurlImpersonateHttpClient(persist_cookies_per_session=cookies, allow_redirects=False,
                                         **({} if verify is True else {"verify": verify}))  # fmt: skip
    if settings.ca_bundle:
        raise InvalidArguments(
            "crawl.ca_bundle needs crawl.http_client = curl: impit can't load a custom CA "
            "(or turn certificate checks off with crawl.verify_tls = false)."
        )
    return ImpitHttpClient(persist_cookies_per_session=cookies, follow_redirects=False, verify=settings.verify_tls)


SITE_CREDENTIAL = "site"


def site_auth_header(settings: CrawlSettings) -> dict[str, str]:
    """`crawl.auth = basic`: the Authorization header for the site's own URLs, password from the keychain."""
    if settings.auth != "basic":
        return {}
    password = credentials.get_secret(SITE_CREDENTIAL)
    if password is None:
        raise AuthRequired(SITE_CREDENTIAL)
    token = base64.b64encode(f"{settings.auth_user or ''}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


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
    robots = RobotsGate(client, settings.robots_user_agent or user_agent or "*", settings.robots_custom,
                        urlsplit(start_url).netloc)  # fmt: skip
    auth = site_auth_header(settings)
    crawl_delay = await robots.crawl_delay(start_url) if settings.robots == "respect" else None

    config = Configuration(log_level="WARNING")
    storage_client = MemoryStorageClient()

    def request(url: str, check: bool) -> Request:
        extra = auth if auth and scope.internal(url) else {}  # the site's password never goes to other sites
        return Request.from_url(url, headers={**headers, **extra} or None, user_data={"check": check})

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
    parser = Parser(
        PageReader(scope, settings, collect, all_settings.rewrite, all_settings.custom), settings.parse_workers
    )
    response_ms: dict[str, int] = {}  # answered requests -> response time, until their handler stores it
    redirect_hops: dict[str, int] = {}  # redirect targets -> steps of the chain that led to them (max_redirects)
    retried: dict[str, int] = {}  # URLs asked again after a 5xx (crawl.retries_5xx), until they are stored
    # Response time around the client's own request: Crawlee's navigation hooks cost ~15% of a big crawl.
    client_crawl = client.crawl
    # crawl.cookies = session: one cookie jar for the whole crawl, like a browser. Crawlee keeps cookies per session
    # of its pool, and requests get different sessions — so the client gets this one instead (the proxy was already
    # picked from Crawlee's session, rotation stays as it was); "none" — no session, no cookies.
    cookie_jar = Session() if settings.cookies == "session" else None

    async def timed_crawl(request, *args, **kwargs):
        kwargs["session"] = cookie_jar
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

    # limits by depth, subdomain and path (crawl.max_urls_per_depth, max_urls_per_subdomain, path_limits): counts of
    # admitted URLs — as many entries as depths, hosts and patterns, whatever the size of the site
    path_limits = [(re.compile(pattern), limit) for pattern, limit in settings.path_limits]
    per_depth: dict[int, int] = {}
    per_host: dict[str, int] = {}
    per_path: dict[int, int] = {}

    def over_limits(url: str, depth: int, crawled: bool) -> bool:
        """Count a URL to crawl against the limits; True — one of them is full, leave it out."""
        if not crawled:
            return False
        host = urlsplit(url).netloc
        matched = [i for i, (pattern, _) in enumerate(path_limits) if pattern.search(url)]
        if settings.max_urls_per_depth is not None and per_depth.get(depth, 0) >= settings.max_urls_per_depth:
            return True
        if settings.max_urls_per_subdomain is not None and per_host.get(host, 0) >= settings.max_urls_per_subdomain:
            return True
        if any(per_path.get(i, 0) >= path_limits[i][1] for i in matched):
            return True
        per_depth[depth] = per_depth.get(depth, 0) + 1
        per_host[host] = per_host.get(host, 0) + 1
        for i in matched:
            per_path[i] = per_path.get(i, 0) + 1
        return False

    if resume:  # the limits count what the crawl already admitted
        for seen_url, seen_depth in resume.seen.items():
            if scope.crawlable(seen_url):
                over_limits(seen_url, seen_depth, True)

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
            check = roles[url] == "check"
            if not start and over_limits(url, depth, not check):
                continue
            depth_of[url] = depth
            if secure := hsts_upgrade(url):  # not fetched: recorded as the browser's own 307 to HTTPS
                writer.queued(url, depth, check)
                writer.add(_hsts_redirect(url, secure, scope), depth=depth)
                writer.add_links([link_row(url, secure, "redirect", scope.internal(secure))])
                upgraded.append(secure)
                continue
            if settings.robots == "respect" and not await robots.allowed(url):
                internal = scope.internal(url)
                if settings.robots_show_internal_blocked if internal else settings.robots_show_external_blocked:
                    writer.queued(url, depth, check)
                    writer.add(_blocked(url, robots, scope), depth=depth)  # never fetched, but part of the report
                continue
            writer.queued(url, depth, check)
            queue.push(url, check)
        if upgraded:
            await admit(upgraded, depth, resources=resources)

    @crawler.router.default_handler
    async def handle(ctx: HttpCrawlingContext) -> None:
        response = ctx.http_response
        body = await response.read()
        check = bool(ctx.request.user_data.get("check"))
        if response.status_code >= 500 and retried.get(ctx.request.url, 0) < settings.retries_5xx:
            retried[ctx.request.url] = retried.get(ctx.request.url, 0) + 1  # asked again later, nothing stored yet
            response_ms.pop(ctx.request.url, None)
            queue.push(ctx.request.url, check)
            return
        retried.pop(ctx.request.url, None)
        if settings.max_page_size_kb is not None and len(body) > settings.max_page_size_kb * 1024:
            check = True  # too big to read: status, headers and size only
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
                    writer.add(_blocked(url, robots, scope), depth=depth)
                    continue
                queue.push(url, check)
        else:
            await admit([start_url], 0, start=True)
            if all_settings.sitemaps.crawl and not listed:  # a fresh crawl: sitemaps first, their URLs one click away
                async for found in sitemaps.read(start_url, all_settings.sitemaps, settings, writer, scope):
                    if all_settings.sitemaps.follow:
                        await admit(found, 1)
        writer.flush()  # the start URL (and a robots verdict on it) is on disk before any fetching
        if not await queue.is_empty():
            async with renderer or contextlib.nullcontext():
                await crawler.run()
    finally:
        parser.close()
        await queue.drop()


def _blocked(url: str, robots: RobotsGate, scope: Scope) -> Page:
    """A URL robots.txt closes: never fetched, stored with the rule that closed it."""
    page = Page.blocked_by_robots(url)
    page.onpage = {"external": not scope.internal(url), "blocked_rule": robots.rule(url)}
    return page


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
    site_auth_header(settings.crawl)  # the site's password, asked for before a crawl is registered
    http_client(settings.crawl)  # the curl client without its extra fails here, before a crawl is registered
    if settings.crawl.ca_bundle and not Path(settings.crawl.ca_bundle).is_file():
        raise InvalidArguments(f"crawl.ca_bundle: no file '{settings.crawl.ca_bundle}'.")
    if settings.crawl.render == "always":
        render.ensure_available()
    if settings.collect.near_duplicates and importlib.util.find_spec("datasketch") is None:
        raise NearDuplicatesUnavailable
    if {"microdata", "rdfa"} & set(settings.collect.structured_data) and importlib.util.find_spec("extruct") is None:
        raise StructuredDataUnavailable
    if settings.sitemaps.crawl:
        sitemaps.ensure_available()
    if any(rule.kind == "xpath" for rule in settings.custom.extract) and importlib.util.find_spec("lxml") is None:
        raise XPathUnavailable


_URL_COLUMNS = ("url", "address", "loc", "адрес")


def _list_lines(text: str) -> list[str]:
    """The URL candidates of a list file, whatever its shape: an XML sitemap (urlset), CSV whose header names
    the URL column (url / address / loc — Screaming Frog's exports say Address), or one URL per line."""
    stripped = text.lstrip()
    if stripped.startswith("<"):
        from xml.etree import ElementTree as ET  # a local file the user chose: the stdlib parser is enough

        try:
            root = ET.fromstring(stripped)  # noqa: S314
        except ET.ParseError as exc:
            raise InvalidArguments(f"The list looks like XML but doesn't parse: {exc}.") from exc
        tag = root.tag.rsplit("}", 1)[-1]
        if tag == "sitemapindex":
            raise InvalidArguments(
                "The list is a sitemap index: give a sitemap with URLs (<urlset>), or crawl the site with "
                "--set sitemaps.crawl=true --set 'sitemaps.urls=[\"<index URL>\"]'."
            )
        return [(el.text or "").strip() for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "loc"]
    lines = stripped.splitlines()
    header = next((line for line in lines if line.strip()), "")
    delimiter = next((d for d in (",", ";", "\t") if d in header), None)
    names = [cell.strip().strip('"').lower() for cell in header.split(delimiter)] if delimiter else []
    column = next((names.index(n) for n in _URL_COLUMNS if n in names), None)
    if column is None:  # no header naming a URL column: one URL per line (a URL may have commas in it)
        return lines
    import csv

    return [row[column] for row in list(csv.reader(lines, delimiter=delimiter or ","))[1:] if len(row) > column]


def read_url_list(text: str) -> list[str]:
    """URLs of a list file — one per line (blank lines and `#` comments skipped), a CSV with a URL column, or an
    XML sitemap — duplicates dropped."""
    urls: dict[str, None] = {}
    bad: list[str] = []
    for number, line in enumerate(_list_lines(text.removeprefix("\ufeff")), 1):
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
