"""Fetch pages without crawling: a URL in, its final URL, status, redirect steps and page data out.

For other tools (`spider fetch`, `rb_spider.fetch`), so none of them needs its own HTTP client,
proxy handling or browser: this reuses the crawl's — impit with a browser fingerprint, proxies
(password from the keychain), User-Agent presets, JS rendering that finds an installed browser,
and `extract.parse_page` for the SEO data. Nothing is written to the crawl database; results are
yielded one by one, in input order, with at most `concurrency` requests in flight, so a list of
any length runs in flat memory. robots.txt is not consulted: the caller named these URLs, the way
`curl` would fetch them.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import AsyncIterator, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import timedelta

from .errors import InvalidArguments
from .extract import normalize_url, parse_page, visible_text
from .markdown import html_to_markdown
from .settings import CrawlSettings

MAX_REDIRECTS = 10
INCLUDE = ("headers", "links", "resources", "text", "markdown", "html")  # on top of the SEO data, always there
# SEO fields of a page, as `pages` names them (see storage.pages)
_SEO_FIELDS = (
    "title", "meta_description", "h1", "h2", "canonical_url", "robots_directives", "word_count",
    "content_md5", "title_count", "h1_count", "h2_count", "canonical_count", "lorem_ipsum", "uncrawlable_outlinks",
)  # fmt: skip


@dataclass
class FetchResult:
    url: str  # as asked (fragment dropped)
    final_url: str | None = None  # after redirects
    status: int | None = None  # the final response's code; None — no response (see `error`)
    redirects: list[dict] = field(default_factory=list)  # [{url, status, location}] — every 3xx step
    content_type: str | None = None
    bytes: int | None = None
    elapsed_ms: int | None = None
    rendered: bool | None = None  # --render: True — data from the browser DOM; False — rendering failed
    seo: dict | None = None  # title, meta_description, h1, canonical_url, robots_directives, word_count…
    refresh_url: str | None = None  # a meta / HTTP Refresh target (not followed)
    headers: dict | None = None
    links: list[dict] | None = None
    resources: list[dict] | None = None
    text: str | None = None
    markdown: str | None = None  # the page's main content (menus, footers, ads aside) as Markdown
    html: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None or k in ("status", "error")}

    def to_markdown(self) -> str:
        """The page as one Markdown document for an LLM: what it is, where it answered, then its content."""
        seo = self.seo or {}
        lines = [f"# {seo.get('title') or self.final_url or self.url}", "", f"- URL: {self.final_url or self.url}"]
        if self.redirects:
            lines.append(f"- Redirected from: {self.url} ({' → '.join(str(r['status']) for r in self.redirects)})")
        if self.error:
            lines.append(f"- Error: {self.error}")
        else:
            lines.append(f"- Status: {self.status}" + (", rendered in a browser" if self.rendered else ""))
        labels = {"meta_description": "Description", "h1": "H1", "canonical_url": "Canonical",
                  "robots_directives": "Robots", "word_count": "Words"}  # fmt: skip
        lines += [f"- {label}: {str(seo[key]).strip(',')}" for key, label in labels.items() if seo.get(key)]
        body = self.markdown if self.markdown is not None else self.text
        if body:
            lines += ["", "---", "", body]
        return "\n".join(lines) + "\n"


def parse_include(value: str | Iterable[str] | None) -> set[str]:
    items = value.split(",") if isinstance(value, str) else list(value or ())
    wanted = {item.strip() for item in items if item.strip()}
    unknown = wanted - set(INCLUDE)
    if unknown:
        raise InvalidArguments(f"Unknown --include {', '.join(sorted(unknown))}: choose from {', '.join(INCLUDE)}.")
    return wanted


class Fetcher:
    """One HTTP client (and, with `render`, one browser) shared by every URL of a run."""

    def __init__(self, settings: CrawlSettings, *, render: bool, include: set[str], proxies: list[str]) -> None:
        from crawlee.http_clients import ImpitHttpClient
        from crawlee.proxy_configuration import ProxyConfiguration

        self.settings, self.include = settings, include
        user_agent = settings.resolved_user_agent
        self.headers = {**settings.headers, **({"User-Agent": user_agent} if user_agent else {})}
        self.client = ImpitHttpClient(follow_redirects=False)
        self.proxies = ProxyConfiguration(proxy_urls=list(proxies)) if proxies else None
        self.timeout = timedelta(seconds=settings.timeout_s)
        self.renderer = None
        if render:
            from .render import Renderer

            self.renderer = Renderer(tabs=settings.render_tabs, wait_ms=settings.render_wait_ms,
                                     timeout_s=settings.timeout_s, user_agent=user_agent, headers=settings.headers,
                                     browser=settings.render_browser)  # fmt: skip

    async def fetch(self, url: str) -> FetchResult:
        result = FetchResult(normalize_url(url))
        started = time.monotonic()
        current = result.url
        try:
            for _ in range(MAX_REDIRECTS + 1):
                proxy = await self.proxies.new_proxy_info(None, None, None) if self.proxies else None
                response = await self.client.send_request(
                    current, headers=self.headers or None, proxy_info=proxy, timeout=self.timeout
                )
                headers = {k.lower(): v for k, v in dict(response.headers).items()}
                body = await response.read()
                page = parse_page(current, response.status_code, headers, b"")  # redirect target only
                if not (300 <= response.status_code < 400 and page.redirect_url):
                    break
                result.redirects.append({"url": current, "status": response.status_code, "location": page.redirect_url})
                current = page.redirect_url
            else:
                result.error = f"more than {MAX_REDIRECTS} redirects"
                result.elapsed_ms = round((time.monotonic() - started) * 1000)
                return result
        except Exception as exc:  # no response: DNS, refused, timeout, TLS — data, not a failed run
            result.error = f"{type(exc).__name__}: {exc}"[:500]
            result.elapsed_ms = round((time.monotonic() - started) * 1000)
            return result
        await self._read(result, current, response.status_code, headers, body)
        result.elapsed_ms = round((time.monotonic() - started) * 1000)
        return result

    async def _read(self, result: FetchResult, url: str, status: int, headers: dict, body: bytes) -> None:
        result.final_url, result.status = url, status
        result.content_type, result.bytes = headers.get("content-type"), len(body)
        source = body
        is_html = "html" in (result.content_type or "text/html")
        if self.renderer is not None and status == 200 and is_html:
            dom = await self.renderer.render(url)
            source, result.rendered = dom or body, dom is not None
        page = parse_page(url, status, headers, source, content_exclude=self.settings.content_exclude)
        result.seo = {key: page.title if key == "title" else page.onpage.get(key) for key in _SEO_FIELDS}
        result.refresh_url = page.refresh_url
        if "headers" in self.include:
            result.headers = headers
        if "links" in self.include:
            result.links = [asdict(link) for link in page.links]
        if "resources" in self.include:
            result.resources = [asdict(resource) for resource in page.resources]
        if "text" in self.include and is_html and source:
            result.text = visible_text(source)
        if "markdown" in self.include and is_html and source:
            result.markdown = html_to_markdown(source, url, self.settings.content_exclude)
        if "html" in self.include and source:
            result.html = source.decode("utf-8", errors="replace")


async def fetch_stream(
    urls: Iterable[str],
    settings: CrawlSettings | None = None,
    *,
    render: bool = False,
    include: str | Iterable[str] | None = None,
    concurrency: int | None = None,
) -> AsyncIterator[FetchResult]:
    """Fetch URLs concurrently, yielding results in input order."""
    from .crawl import proxy_urls

    settings = settings or CrawlSettings()
    wanted = parse_include(include)
    if render:
        from .render import ensure_available

        ensure_available()
    fetcher = Fetcher(settings, render=render, include=wanted, proxies=proxy_urls(settings))
    limit = asyncio.Semaphore(concurrency or settings.concurrency)

    async def one(url: str) -> FetchResult:
        async with limit:
            return await fetcher.fetch(url)

    window: deque[asyncio.Task[FetchResult]] = deque()
    async with fetcher.renderer or contextlib.nullcontext():
        for url in urls:
            window.append(asyncio.create_task(one(url)))
            if len(window) >= 2 * (concurrency or settings.concurrency):  # bounded: flat memory for any list
                yield await window.popleft()
        while window:
            yield await window.popleft()


def fetch_many(urls: Iterable[str], settings: CrawlSettings | None = None, **options) -> Iterator[FetchResult]:
    """`fetch_stream` for synchronous code; results arrive as they are ready, in input order."""
    stream = fetch_stream(urls, settings, **options)
    loop = asyncio.new_event_loop()
    try:
        while True:
            try:
                yield loop.run_until_complete(anext(stream))
            except StopAsyncIteration:
                return
    finally:
        loop.run_until_complete(stream.aclose())
        loop.close()


def fetch(url: str, settings: CrawlSettings | None = None, **options) -> FetchResult:
    """One page: its final URL, status, redirect steps and data (see `FetchResult`)."""
    return next(fetch_many([url], settings, **options))
