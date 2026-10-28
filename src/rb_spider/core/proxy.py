"""Proxies for all traffic to the sites (`crawl.proxy_*` keys): pages, robots.txt, sitemaps, the browser.

- `Proxies` — the addresses as Crawlee's proxy configuration: `rotate` (the next one for every request) or
  `failover` (the first that works; the next one when it dies — a mobile proxy's HTTP and SOCKS5 doors).
  `off` — straight to the sites, only when crawl.proxy_fallback = direct (or a person said so).
- `open_proxies` — the check before a crawl or `spider fetch`: a dead proxy is never bypassed silently. Each address:
  a TCP connection to the proxy itself (crawl.proxy_connect_timeout_s), then `proxy_fails` — the same request
  through the proxy and straight to the site at once: only a proxy that fails where the site answers is blamed.
  All addresses dead and change-IP links set: one new IP, then the check again. The result is remembered between
  runs (`proxy_state`, crawl.proxy_state_ttl_s): an address checked lately is not checked again.
- `Breaker` — crawl.proxy_max_failures requests through the proxy in a row with no answer (a proxy failure or a
  timeout) during a run: one `proxy_fails` check says whose they were.
- `IpChanger` — crawl.proxy_change_ip_urls: when the site blocks (crawl.proxy_change_ip_on: 403, 429…), one
  request to the provider's links (tried in turn) gets the modem a new IP, and the blocked requests ask again.

Secrets never sit in the config: `{password}` in an address and `{key}` in a change-IP link are filled from
the keychain or the environment (`spider auth login --provider proxy` / `proxy_key`, or
SPIDER_PROXY_API_KEY / SPIDER_PROXY_KEY_API_KEY on a server without a keychain).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import unquote, urlsplit

from crawlee import Request
from crawlee.errors import ProxyError
from crawlee.http_clients import HttpClient
from crawlee.proxy_configuration import ProxyConfiguration, ProxyInfo

from ..providers import secrets
from . import proxy_state
from .errors import AuthRequired, InvalidArguments, ProxyUnavailable
from .settings import CrawlSettings

log = logging.getLogger(__name__)

PROXY_CREDENTIAL = "proxy"
KEY_CREDENTIAL = "proxy_key"
PROXY_AUTH_REQUIRED = 407
UNPRODUCTIVE_CHANGES = 3  # IP changes in a row the site answered only with blocks: it blocks every IP, stop changing
_ONLINE_POLL_S = 2.0
CHECK_URL = "http://ipinfo.io/json"  # `check_now` asks it through each address: plain http, a proxy forwards it as is
CHECK_TIMEOUT_S = 10.0  # the check's requests wait at most this long, or crawl.timeout_s when it is shorter


def _secret(urls: list[str], placeholder: str, credential: str) -> str | None:
    """The secret `placeholder` stands for in `urls`; None — they have no placeholder."""
    if not any(placeholder in url for url in urls):
        return None
    secret = secrets.password(credential)
    if secret is None:
        raise AuthRequired(credential)
    return secret


def _filled(urls: list[str], placeholder: str, credential: str) -> list[str]:
    secret = _secret(urls, placeholder, credential)
    return [url.replace(placeholder, secret) for url in urls] if secret else list(urls)


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

    def __init__(self, urls: list[str], mode: str, concurrency: int) -> None:
        super().__init__(new_url_function=_unused)  # never called: new_proxy_info is ours
        self.urls, self.mode, self.current, self.off = list(urls), mode, 0, False
        self._next = 0
        self._slots = asyncio.Semaphore(concurrency)
        self._said = False

    def limited(self, info: ProxyInfo | None) -> contextlib.AbstractAsyncContextManager:
        """A request through a proxy (`info`) waits for a free slot (crawl.proxy_concurrency); one without — never."""
        return self._slots if info else contextlib.nullcontext()

    def say(self, problem: str, action: str) -> None:
        """The one line of the run on stderr (logging, so --json keeps stdout clean): what failed, what spider does."""
        if not self._said:
            self._said = True
            log.warning("the proxy doesn't work (%s): %s", problem, action)

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

    def replaced(self, url: str) -> bool:
        """A request sent through `url` before that proxy was dropped: ask it again, the new way."""
        return self.off or (self.mode == "failover" and url != self.active)

    def go_direct(self, problem: str) -> None:
        self.say(problem, "going on without it, the site sees this IP")
        self.off = True

    def drop(self, problem: str, fallback: str) -> bool:
        """The active address is dead: True — going on (failover: the next address; none left and
        crawl.proxy_fallback = direct: without the proxy); False — stop."""
        if self.advance():
            log.warning("the proxy doesn't work (%s): going through %s", problem, self.address)
            return True
        if fallback == "direct":
            self.go_direct(problem)
            return True
        self.say(problem, "stopping")
        return False


def proxy_failure(error: BaseException) -> bool:
    """The proxy failed, not the site: through a proxy every connection goes to the proxy, so a refused or
    unresolved one is its, as is its own refusal (Crawlee's ProxyError: 407, a failed tunnel)."""
    return isinstance(error, ProxyError) or type(error).__name__ == "ConnectError" or "proxy" in str(error).lower()


def no_answer(error: BaseException) -> bool:
    """A request through a proxy that got no answer: the proxy's failure, or a timeout (the proxy or the site — the
    `Breaker` finds out whose)."""
    return proxy_failure(error) or isinstance(error, TimeoutError)


def check_proxy_answer(status: int) -> None:
    """An http:// URL goes through the proxy as a plain request: the proxy's refusal comes back as a response."""
    if status == PROXY_AUTH_REQUIRED:
        raise ProxyError(f"the proxy answered {PROXY_AUTH_REQUIRED}: its password is wrong or it isn't paid")


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


async def _probe(settings: CrawlSettings, client: HttpClient, target: str, info: ProxyInfo | None,
                 timeout_s: float | None = None) -> None:  # fmt: skip
    """One request (through a proxy with `info`); raises what a proxy failure raises (a 407 answer included)."""
    response = await client.send_request(target, headers=_headers(settings) or None, proxy_info=info,
                                         timeout=timedelta(seconds=timeout_s or settings.timeout_s))  # fmt: skip
    if info is not None:
        check_proxy_answer(response.status_code)


async def _connects(proxy: str, timeout_s: float) -> str | None:
    """A TCP connection to the proxy itself (host:port), as impit has no connect timeout; None — it opened."""
    info = proxy_info(proxy)
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(info.hostname, info.port), timeout_s)
    except TimeoutError:
        return f"no TCP connection in {timeout_s:g} s"
    except OSError as exc:
        return f"no TCP connection: {exc.strerror or exc}"
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return None


async def proxy_fails(settings: CrawlSettings, client: HttpClient, url: str, proxy: str) -> str | None:
    """The check of one proxy address on `url`'s site; why it failed, None — it works.

    A TCP connection to the proxy first (crawl.proxy_connect_timeout_s). Then robots.txt of the site through the
    proxy and straight, at once: no answer through the proxy while the site answers straight — the proxy failed;
    its 407 (wrong password, not paid) — too. No answer either way (a refused tunnel included: a proxy can't reach
    a site that is down) — the site's failure, not the proxy's. The straight answer only checks: it is no page data.
    """
    problem = await _connects(proxy, settings.proxy_connect_timeout_s)
    if problem:
        return problem
    target, timeout_s = _robots_url(url), min(settings.timeout_s, CHECK_TIMEOUT_S)
    through, straight = await asyncio.gather(
        _probe(settings, client, target, proxy_info(proxy), timeout_s),
        _probe(settings, client, target, None, timeout_s),
        return_exceptions=True,
    )
    if through is None or not (straight is None or str(PROXY_AUTH_REQUIRED) in why(through)):
        return None
    return f"no answer in {timeout_s:g} s, the site answers straight" if isinstance(through, TimeoutError) \
        else why(through)  # fmt: skip


async def _verdict(settings: CrawlSettings, client: HttpClient, url: str, proxy: str) -> tuple[str | None, bool]:
    """(why `proxy` is dead | None — it works, whether this check is new): from the remembered check when it is
    younger than crawl.proxy_state_ttl_s (no connection, not new), else a new one (`proxy_fails`), remembered."""
    known = proxy_state.fresh(proxy, settings.proxy_state_ttl_s)
    if known is not None:
        return (
            None if known["status"] == "alive" else f"{known['reason']} (remembered from {known['checked_at']})"
        ), False
    problem = await proxy_fails(settings, client, url, proxy)
    proxy_state.record(proxy, problem)
    return problem, True


async def _answers(settings: CrawlSettings, client: HttpClient, proxy: str) -> str | None:
    """One TCP connection to `proxy` and one request through it, to `CHECK_URL`; why it fails, None — it
    answers. The site is not known here, so there is no straight request: the address alone is judged."""
    problem = await _connects(proxy, settings.proxy_connect_timeout_s)
    if problem:
        return problem
    try:
        await _probe(settings, client, CHECK_URL, proxy_info(proxy), min(settings.timeout_s, CHECK_TIMEOUT_S))
    except Exception as exc:
        return why(exc)
    return None


async def check_now(settings: CrawlSettings) -> list[tuple[str, str | None]]:
    """`spider auth status --check`: every address of the settings checked at once (`_answers`), each within
    CHECK_TIMEOUT_S and so the whole within it too; the results are remembered. [(address, why it fails | None)]."""
    from .crawl import http_client

    client = http_client(settings)

    async def one(proxy: str) -> tuple[str, str | None]:
        try:
            problem = await asyncio.wait_for(_answers(settings, client, proxy), CHECK_TIMEOUT_S)
        except TimeoutError:
            problem = f"no answer in {CHECK_TIMEOUT_S:g} s"
        proxy_state.record(proxy, problem)
        return proxy, problem

    return list(await asyncio.gather(*(one(proxy) for proxy in proxy_urls(settings))))


async def _dead_addresses(
    settings: CrawlSettings, client: HttpClient, proxies: Proxies, url: str
) -> tuple[list[str], bool]:
    """Each address checked (`proxy_fails`); (the problems that leave the proxies dead, [] — they work; whether
    a new check made any of them — not only the remembered state).

    rotate: every address must work. failover: the first that works becomes the active one.
    """
    problems: list[str] = []
    found_now = False
    for index, proxy in enumerate(proxies.urls):
        problem, new = await _verdict(settings, client, url, proxy)
        if problem:
            found_now = found_now or new
            problems.append(f"{_address(proxy)} — {problem}")
            if settings.proxy_mode == "rotate":
                return problems, found_now  # every address is used: one dead is enough
            continue  # failover: the next one
        if settings.proxy_mode == "failover":
            proxies.current = index
            if problems:
                log.warning("the proxy doesn't work (%s): going through %s", "; ".join(problems), proxies.address)
            return [], False
    return problems, found_now


async def open_proxies(
    settings: CrawlSettings, client: HttpClient, url: str, ask: Callable[[str], bool] | None = None
) -> tuple[Proxies | None, str | None]:
    """The proxies after the check of each address on `url`'s site (`proxy_fails`); (proxies, why they're off).

    rotate: every address must work. failover: the first that works is used. All dead and
    crawl.proxy_change_ip_urls set and a check of this run found them dead (not only the remembered state): one new
    IP, then the check again. Still dead: crawl.proxy_fallback = direct, or
    `ask` (a person in a terminal) says yes — go without it; otherwise ProxyUnavailable.
    """
    urls = proxy_urls(settings)
    if not urls:
        return None, None
    proxies = Proxies(urls, settings.proxy_mode, settings.proxy_concurrency)
    problems, found_now = await _dead_addresses(settings, client, proxies, url)
    if problems and found_now and settings.proxy_change_ip_urls:
        refused = await IpChanger(settings, client, proxies, url).renew()
        problems, _ = await _dead_addresses(settings, client, proxies, url)
        if problems and refused:
            problems.append(f"change IP — {refused}")
    if not problems:
        return proxies, None
    problem = "; ".join(problems)
    if settings.proxy_fallback == "direct" or (ask is not None and ask(problem)):
        proxies.go_direct(problem)
        return proxies, problem
    proxies.say(problem, "stopping")
    raise ProxyUnavailable(problem)


class Breaker:
    """crawl.proxy_max_failures requests through the proxy in a row with no answer (`no_answer`), then one check
    (`proxy_fails` on the last one's site) says whose they were. An answer through the proxy resets the count —
    only one sent after the last miss: an answer that was on its way before says nothing of the proxy now.

    The caller may `hold` items (pages it doesn't store yet): they come back with the verdict — to store when the
    proxy works, to ask again when it is dead.
    """

    def __init__(self, settings: CrawlSettings, client: HttpClient) -> None:
        self.settings, self.client = settings, client
        self.misses = 0
        self.held: list[Any] = []
        self._last_miss = float("-inf")
        self._checking = False

    def hold(self, item: Any) -> None:
        self.held.append(item)

    def answered(self, sent: float) -> list[Any]:
        """An answer through the proxy to a request sent at `sent` (time.monotonic): the held items to store."""
        if sent <= self._last_miss:
            return []
        self.misses = 0
        return self._release()

    def release(self) -> list[Any]:
        """The run's end: what is held, to store — not enough misses in a row to blame the proxy."""
        return self._release()

    async def missed(self, url: str, proxy: str) -> tuple[str | None, list[Any]]:
        """A request to `url` through `proxy` got no answer.

        (why the proxy is dead, the held items to ask again) or (None, the held items to store — maybe none yet).
        """
        self.misses += 1
        self._last_miss = time.monotonic()
        if self.misses < self.settings.proxy_max_failures or self._checking:
            return None, []
        self._checking = True
        try:
            problem = await proxy_fails(self.settings, self.client, url, proxy)
            proxy_state.record(proxy, problem)
        finally:
            self._checking = False
        misses, self.misses = self.misses, 0
        if problem is None:
            log.info("%d requests through the proxy without an answer, but the site fails straight too", misses)
            return None, self._release()
        return f"{_address(proxy)}: {misses} proxy errors in a row, then the check: {problem}", self._release()

    def _release(self) -> list[Any]:
        items, self.held = self.held, []
        return items


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
        self._key = _secret(settings.proxy_change_ip_urls, "{key}", KEY_CREDENTIAL)
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
                new_ip = await self._ask_provider([])
                self._last = time.monotonic()
                if new_ip is None:
                    return False  # no link agreed: this answer stays, the next block tries again
                # the kept-alive connections went through the old IP's tunnel and are dead: new ones from here
                await self.client.cleanup()
                await self._wait_online()
            finally:
                self._idle.set()
            proxy_state.record_ip_change(self.proxies.urls)
            self.generation += 1
            self.changes += 1
            self.last_ip = new_ip or self.last_ip
            log.warning("the site blocks: new proxy IP %s (change %d)", new_ip or "?", self.changes)
            return True

    async def renew(self) -> str | None:
        """One new IP for a dead proxy, outside the site's blocks, and the wait until it answers; None — the provider
        agreed, else its refusals (the key scrubbed)."""
        refusals: list[str] = []
        if await self._ask_provider(refusals) is None:
            return "; ".join(refusals)
        proxy_state.record_ip_change(self.proxies.urls)
        await self.client.cleanup()
        await self._wait_online()
        return None

    def _give_up(self, reason: str) -> bool:
        self.gave_up = reason
        log.warning("stopped changing the proxy IP (%s): blocked answers are stored as they are", reason)
        return False

    async def _ask_provider(self, refusals: list[str]) -> str | None:
        """Each change-IP link in turn until one agrees; the new IP ("" — the provider didn't say), None — none did.

        The link goes to the provider straight, not through the proxy: it is its API, not the site. Why each link
        refused goes to the log and to `refusals`, the key scrubbed: a provider may repeat the link in its answer.
        """
        for link in self.links:
            try:
                response = await self.client.send_request(link, timeout=timedelta(seconds=self.settings.timeout_s))
                body = await response.read()
            except Exception as exc:
                self._refused(refusals, link, f"failed: {why(exc)}")
                continue
            if not 200 <= response.status_code < 300:
                self._refused(refusals, link, f"answered {response.status_code}: {body.decode(errors='replace')}")
                continue
            try:
                data = json.loads(body)
            except ValueError:
                return ""  # a plain-text "OK"
            if isinstance(data, dict) and str(data.get("status", "ok")).lower() not in ("ok", "true", "success"):
                self._refused(refusals, link, f"refused: {data}")
                continue
            return str(data.get("new_ip") or "") if isinstance(data, dict) else ""
        return None

    def _refused(self, refusals: list[str], link: str, reason: str) -> None:
        text = f"{urlsplit(link).netloc} {reason.replace(self._key, '{key}') if self._key else reason}"[:300]
        log.warning("change-IP link %s", text)
        refusals.append(text)

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
