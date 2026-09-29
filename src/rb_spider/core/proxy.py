"""Proxies for all traffic to the sites (`crawl.proxy_*` keys): pages, robots.txt, sitemaps, the browser.

- `Proxies` — the addresses as Crawlee's proxy configuration: `rotate` (the next one for every request) or
  `failover` (the first that works; the next one when it dies — a mobile proxy's HTTP and SOCKS5 doors).
  `off` — straight to the sites, only when crawl.proxy_fallback = direct (or a person said so).
- `open_proxies` — the check before a crawl or `spider fetch`: a dead proxy is never bypassed silently.
- `IpChanger` — crawl.proxy_change_ip_urls: when the site blocks (crawl.proxy_change_ip_on: 403, 429…), one
  request to the provider's links (tried in turn) gets the modem a new IP, and the blocked requests ask again.

Secrets never sit in the config: `{password}` in an address and `{key}` in a change-IP link are filled from
the keychain or the environment (`spider auth login --provider proxy` / `proxy_key`, or
SPIDER_PROXY_API_KEY / SPIDER_PROXY_KEY_API_KEY on a server without a keychain).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import timedelta
from urllib.parse import unquote, urlsplit

from crawlee import Request
from crawlee.errors import ProxyError
from crawlee.http_clients import HttpClient
from crawlee.proxy_configuration import ProxyConfiguration, ProxyInfo

from ..providers import secrets
from .errors import AuthRequired, InvalidArguments, ProxyUnavailable
from .settings import CrawlSettings

log = logging.getLogger(__name__)

PROXY_CREDENTIAL = "proxy"
KEY_CREDENTIAL = "proxy_key"
PROXY_AUTH_REQUIRED = 407
UNPRODUCTIVE_CHANGES = 3  # IP changes in a row the site answered only with blocks: it blocks every IP, stop changing
_ONLINE_POLL_S = 2.0


def _filled(urls: list[str], placeholder: str, credential: str) -> list[str]:
    if not any(placeholder in url for url in urls):
        return list(urls)
    secret = secrets.password(credential)
    if secret is None:
        raise AuthRequired(credential)
    return [url.replace(placeholder, secret) for url in urls]


def proxy_urls(settings: CrawlSettings) -> list[str]:
    """`crawl.proxy_urls` with `{password}` filled from the keychain (`spider auth login --provider proxy`)."""
    return _filled(settings.proxy_urls, "{password}", PROXY_CREDENTIAL)


def change_ip_urls(settings: CrawlSettings) -> list[str]:
    """`crawl.proxy_change_ip_urls` with `{key}` filled (`spider auth login --provider proxy_key`)."""
    return _filled(settings.proxy_change_ip_urls, "{key}", KEY_CREDENTIAL)


def proxy_info(url: str) -> ProxyInfo:
    """A proxy address as Crawlee's ProxyInfo, whatever its scheme (http, https, socks5, socks5h)."""
    parts = urlsplit(url)
    default = {"http": 80, "https": 443}.get(parts.scheme, 1080)
    return ProxyInfo(url=url, scheme=parts.scheme, hostname=parts.hostname or "", port=parts.port or default,
                     username=unquote(parts.username or ""), password=unquote(parts.password or ""))  # fmt: skip


def _address(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.hostname}:{parts.port}" if parts.port else str(parts.hostname)


def _unused(session_id: str | None = None, request: Request | None = None) -> str | None:
    return None


class Proxies(ProxyConfiguration):
    """`crawl.proxy_urls` for all traffic to the sites, rotated or one after another (crawl.proxy_mode).

    The addresses are handed out here, not by Crawlee's configuration: it accepts only http(s) proxies, and a
    mobile proxy's second door is often SOCKS5 (impit and httpx go through it).
    """

    def __init__(self, urls: list[str], mode: str = "rotate") -> None:
        super().__init__(new_url_function=_unused)  # never called: new_proxy_info is ours
        self.urls, self.mode, self.current, self.off = list(urls), mode, 0, False
        self._next = 0

    async def new_proxy_info(
        self, session_id: str | None, request: Request | None, proxy_tier: int | None
    ) -> ProxyInfo | None:
        if self.off:
            return None
        if self.mode == "failover":
            return proxy_info(self.urls[self.current])
        self._next = (self._next + 1) % len(self.urls)
        return proxy_info(self.urls[self._next])

    async def exit_proxy(self) -> ProxyInfo | None:
        """The proxy the site sees now: the active address's, None when off."""
        return None if self.off else await self.info(self.urls[self.current])

    async def info(self, url: str | None = None) -> ProxyInfo | None:
        """One request's proxy: `url`'s, or the next one as a page would get it."""
        return proxy_info(url) if url else await self.new_proxy_info(None, None, None)

    @property
    def active(self) -> str | None:
        """The one proxy of the clients that can't rotate: the browser, rb-sitemap-xml."""
        return None if self.off else self.urls[self.current]

    @property
    def address(self) -> str:
        return _address(self.urls[self.current])

    def advance(self) -> bool:
        """failover: on to the next address; False — there is none (or the mode rotates)."""
        if self.mode != "failover" or self.current + 1 >= len(self.urls):
            return False
        self.current += 1
        return True


def proxy_failure(error: BaseException) -> bool:
    """The proxy failed, not the site: through a proxy every connection goes to the proxy, so a refused or
    unresolved one is its, as is its own refusal (Crawlee's ProxyError: 407, a failed tunnel)."""
    return isinstance(error, ProxyError) or type(error).__name__ == "ConnectError" or "proxy" in str(error).lower()


def why(error: BaseException) -> str:
    """The first line of what went wrong: Crawlee's ProxyError from a client says nothing itself, its cause does."""
    cause = error.__cause__ if error.__cause__ and not str(error) else error
    return (str(cause).strip().splitlines() or [type(cause).__name__])[0][:200]


def _headers(settings: CrawlSettings) -> dict[str, str]:
    user_agent = settings.resolved_user_agent
    return {**settings.headers, **({"User-Agent": user_agent} if user_agent else {})}


def _robots_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


async def _probe(settings: CrawlSettings, client: HttpClient, target: str, info: ProxyInfo | None) -> None:
    """One request through a proxy; raises what a proxy failure raises (a 407 answer included)."""
    response = await client.send_request(target, headers=_headers(settings) or None, proxy_info=info,
                                         timeout=timedelta(seconds=settings.timeout_s))  # fmt: skip
    if response.status_code == PROXY_AUTH_REQUIRED:
        raise ProxyError(f"the proxy answered {PROXY_AUTH_REQUIRED}: its password is wrong or it isn't paid")


async def open_proxies(
    settings: CrawlSettings, client: HttpClient, url: str, ask: Callable[[str], bool] | None = None
) -> tuple[Proxies | None, str | None]:
    """The proxies after a check request through each (robots.txt of `url`'s site); (proxies, why they're off).

    rotate: every address must work. failover: the first that works is used. A dead proxy:
    crawl.proxy_fallback = direct, or `ask` (a person in a terminal) says yes — go without it; otherwise
    ProxyUnavailable. Other failures (a timeout, the site's TLS) are the site's: the crawl records them.
    """
    urls = proxy_urls(settings)
    if not urls:
        return None, None
    proxies = Proxies(urls, settings.proxy_mode)
    target = _robots_url(url)
    problems: list[str] = []
    for index, proxy in enumerate(urls):
        try:
            await _probe(settings, client, target, await proxies.info(proxy))
        except Exception as exc:
            if proxy_failure(exc):
                problems.append(f"{_address(proxy)} — {why(exc)}")
                if settings.proxy_mode == "rotate":
                    break  # every address is used: one dead is enough
                continue  # failover: the next one
            # any other failure is the site's: this proxy works
        if settings.proxy_mode == "failover":
            proxies.current = index
            if problems:
                log.warning("the proxy doesn't work (%s): going through %s", "; ".join(problems), proxies.address)
            return proxies, None
    if not problems:
        return proxies, None
    problem = "; ".join(problems)
    if settings.proxy_fallback == "direct" or (ask is not None and ask(problem)):
        log.warning("the proxy doesn't work (%s): going on without it, the site sees this IP", problem)
        proxies.off = True
        return proxies, problem
    raise ProxyUnavailable(problem)


def check_render_proxy(settings: CrawlSettings) -> None:
    """Chromium takes no SOCKS5 proxy with a password: the browser needs the HTTP address first."""
    parts = urlsplit(settings.proxy_urls[0]) if settings.proxy_urls else None
    if parts and parts.scheme.startswith("socks") and parts.username:
        raise InvalidArguments(
            "The browser (crawl.render) can't use a SOCKS5 proxy with a password: put the proxy's HTTP address "
            "first in crawl.proxy_urls."
        )


class IpChanger:
    """A new IP when the site blocks (crawl.proxy_change_ip_*), for a proxy whose IP changes on request.

    A request answered with a blocking status (`blocked`) calls `change` with the generation it was sent in: the
    first of a burst asks the provider — each link of crawl.proxy_change_ip_urls in turn until one agrees — and
    waits until the proxy answers again; the rest of the burst just ask again. While an IP changes, new requests
    wait (`idle`). Changes are spaced by crawl.proxy_change_ip_min_interval_s. After UNPRODUCTIVE_CHANGES changes
    in a row that answered only with blocks (a late answer counts for the IP it was sent from), or crawl.proxy_change_ip_max changes, it gives up: blocked answers are
    stored as they are.
    """

    def __init__(self, settings: CrawlSettings, client: HttpClient, proxies: Proxies, site_url: str) -> None:
        self.settings, self.client, self.proxies = settings, client, proxies
        self.links = change_ip_urls(settings)
        self.block = set(settings.proxy_change_ip_on)
        self.target = _robots_url(site_url)
        self.generation = self.changes = 0
        self.answers: dict[int, int] = {}  # generation -> answers that weren't blocks, credited to when they were sent
        self.gave_up: str | None = None
        self.last_ip: str | None = None
        self._last = -settings.proxy_change_ip_min_interval_s
        self._lock = asyncio.Lock()
        self._idle = asyncio.Event()
        self._idle.set()

    def blocked(self, status: int) -> bool:
        return self.gave_up is None and not self.proxies.off and status in self.block

    def answered(self, generation: int) -> None:
        """A response that isn't a block, to a request sent in `generation`: that IP worked."""
        self.answers[generation] = self.answers.get(generation, 0) + 1

    async def idle(self) -> None:
        await self._idle.wait()

    async def change(self, generation: int) -> bool:
        """For a blocked answer sent in `generation`: True — the IP is new, ask again; False — keep the answer."""
        async with self._lock:
            if self.generation != generation:
                return self.gave_up is None  # changed while this one was on its way
            if self.gave_up is not None:
                return False
            recent = range(self.generation - UNPRODUCTIVE_CHANGES + 1, self.generation + 1)
            if self.generation >= UNPRODUCTIVE_CHANGES and not any(self.answers.get(g) for g in recent):
                return self._give_up(f"{UNPRODUCTIVE_CHANGES} new IPs in a row were blocked at once")
            if self.changes >= self.settings.proxy_change_ip_max:
                return self._give_up(f"crawl.proxy_change_ip_max = {self.settings.proxy_change_ip_max} reached")
            self._idle.clear()
            try:
                await asyncio.sleep(
                    max(0.0, self._last + self.settings.proxy_change_ip_min_interval_s - time.monotonic())
                )
                new_ip = await self._ask_provider()
                self._last = time.monotonic()
                if new_ip is None:
                    return False  # no link agreed: this answer stays, the next block tries again
                # the kept-alive connections went through the old IP's tunnel and are dead: new ones from here
                await self.client.cleanup()
                await self._wait_online()
            finally:
                self._idle.set()
            self.generation += 1
            self.changes += 1
            self.last_ip = new_ip or self.last_ip
            log.warning("the site blocks: new proxy IP %s (change %d)", new_ip or "?", self.changes)
            return True

    def _give_up(self, reason: str) -> bool:
        self.gave_up = reason
        log.warning("stopped changing the proxy IP (%s): blocked answers are stored as they are", reason)
        return False

    async def _ask_provider(self) -> str | None:
        """Each change-IP link in turn until one agrees; the new IP ("" — the provider didn't say), None — none did.

        The link goes to the provider straight, not through the proxy: it is its API, not the site.
        """
        for link in self.links:
            try:
                response = await self.client.send_request(link, timeout=timedelta(seconds=self.settings.timeout_s))
                body = await response.read()
            except Exception as exc:
                log.warning("change-IP link %s failed: %s", urlsplit(link).netloc, why(exc))
                continue
            if not 200 <= response.status_code < 300:
                log.warning("change-IP link %s answered %d", urlsplit(link).netloc, response.status_code)
                continue
            try:
                data = json.loads(body)
            except ValueError:
                return ""  # a plain-text "OK"
            if isinstance(data, dict) and str(data.get("status", "ok")).lower() not in ("ok", "true", "success"):
                log.warning("change-IP link %s refused: %s", urlsplit(link).netloc, str(data)[:200])
                continue
            return str(data.get("new_ip") or "") if isinstance(data, dict) else ""
        return None

    async def _wait_online(self) -> None:
        """Until the proxy answers again (the modem reconnects), at most crawl.proxy_change_ip_wait_s."""
        deadline = time.monotonic() + self.settings.proxy_change_ip_wait_s
        while True:
            try:
                await _probe(self.settings, self.client, self.target, await self.proxies.info(self.proxies.active))
                return
            except Exception as exc:
                if time.monotonic() >= deadline:
                    log.warning("the proxy isn't back %ss after the IP change: %s", self.settings.proxy_change_ip_wait_s,
                                why(exc))  # fmt: skip
                    return
            await asyncio.sleep(_ONLINE_POLL_S)


def ip_changer(settings: CrawlSettings, client: HttpClient, proxies: Proxies | None, site_url: str) -> IpChanger | None:
    """The crawl's IpChanger, when it has proxies and change-IP links."""
    if proxies is None or not settings.proxy_change_ip_urls:
        return None
    return IpChanger(settings, client, proxies, site_url)
