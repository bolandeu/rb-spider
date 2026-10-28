"""crawl.proxy_urls carries all traffic to the site — pages, robots.txt, sitemaps, the browser — and a dead proxy
(crawl.proxy_fallback) stops the crawl or is dropped, never silently bypassed.

The polygon's proxy (`polygon.proxy`) answers for `polygon.test`, a name that resolves nowhere: a request that
goes around the proxy fails.
"""

from __future__ import annotations

import importlib.util
import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa

from rb_spider.core import storage
from rb_spider.core.crawl import crawl_site, register_crawl, run_crawl
from rb_spider.core.errors import ProxyUnavailable
from rb_spider.core.settings import CrawlSettings, Settings, SitemapSettings
from rb_spider.fetch import fetch, fetch_many

from . import polygon


@pytest.fixture(scope="module")
def upstream():
    with polygon.serve() as url:
        yield url


@pytest.fixture
def proxy(upstream: str, monkeypatch):
    monkeypatch.setenv("SPIDER_PROXY_API_KEY", polygon.Proxy.PASSWORD)
    with polygon.proxy(upstream) as found:
        yield found


def _crawl(proxy: polygon.Proxy, **crawl) -> CrawlSettings:
    return CrawlSettings(proxy_urls=[proxy.url], **crawl)


def _pages(engine, crawl_id: int) -> dict[str, tuple[int | None, str | None]]:
    query = sa.select(storage.pages.c.url, storage.pages.c.status_code, storage.pages.c.error)
    with engine.connect() as conn:
        return {
            url: (status, error)
            for url, status, error in conn.execute(query.where(storage.pages.c.crawl_id == crawl_id))
        }


def _proxy_errors(proxy: polygon.Proxy, pages: dict, base: str | None = None) -> list[str]:
    """The polygon's pages stored with the proxy's failure (external URLs may fail through it: their own error)."""
    return [url for url, (status, error) in pages.items() if url.startswith(base or proxy.base())
            and (status == 407 or (error and "proxy" in error.lower()))]  # fmt: skip


def _status(engine, crawl_id: int) -> str:
    return storage.get_crawl(engine, crawl_id)[0].status


def test_pages_robots_and_sitemaps_all_go_through_the_proxy(proxy: polygon.Proxy) -> None:
    pytest.importorskip("rb_sitemap_xml")
    settings = Settings(crawl=_crawl(proxy, max_urls=20), sitemaps=SitemapSettings(crawl=True))
    with storage.database() as engine:
        result = crawl_site(engine, f"{proxy.base()}/sm/", "polygon", settings)
        pages = _pages(engine, result.crawl_id)
        with engine.connect() as conn:
            files = conn.execute(sa.text("SELECT url, error FROM spider_sitemap_files")).all()
    assert result.status == "finished" and result.proxy_down is None
    assert pages[f"{proxy.base()}/sm/"][0] == 200
    read = {url.removeprefix(proxy.base()) for url, error in files if error is None}
    assert {"/sm/sitemap.xml", "/sm/pages.xml"} <= read  # the sitemaps came through the proxy
    paths = {path for _, path in proxy.seen}
    assert {"/robots.txt", "/sm/sitemap.xml", "/sm/"} <= paths


@pytest.mark.skipif(importlib.util.find_spec("playwright") is None, reason="extra rb-spider[render]")
def test_the_browser_goes_through_the_proxy_too(proxy: polygon.Proxy) -> None:
    page = fetch(f"{proxy.base()}/js/title-added", CrawlSettings(proxy_urls=[proxy.url]), render=True)
    assert page.rendered is True and page.seo and "js-title-added" in page.seo["title"]
    agents = [agent for agent, path in proxy.seen if path == "/js/title-added"]
    assert len(agents) == 2 and any("Chrome" in agent for agent in agents)  # the plain request, then the browser


def test_the_browser_refuses_a_socks_proxy_with_a_password(monkeypatch) -> None:
    pytest.importorskip("playwright")
    # no keychain on a server: the password comes from the environment
    monkeypatch.setenv("SPIDER_PROXY_API_KEY", polygon.Proxy.PASSWORD)
    settings = CrawlSettings(proxy_urls=["socks5h://user:{password}@127.0.0.1:1"], render="always")
    with storage.database() as engine, pytest.raises(Exception, match="SOCKS5"):
        register_crawl(engine, "http://polygon.test/", "polygon", Settings(crawl=settings))


def test_a_dead_proxy_stops_the_crawl_before_it_starts(proxy: polygon.Proxy) -> None:
    proxy.dead = True
    with storage.database() as engine:
        crawl_id = register_crawl(engine, f"{proxy.base()}/a", "polygon", Settings(crawl=_crawl(proxy)))
        with pytest.raises(ProxyUnavailable, match="407"):
            run_crawl(engine, crawl_id)
        assert _status(engine, crawl_id) == "interrupted" and _pages(engine, crawl_id) == {}
        proxy.dead = False  # paid again: the crawl goes on where it stopped
        assert run_crawl(engine, crawl_id).status == "finished"
        assert _pages(engine, crawl_id)[f"{proxy.base()}/a"][0] == 200


def test_asked_in_a_terminal_the_crawl_goes_on_without_the_proxy(proxy: polygon.Proxy, upstream: str) -> None:
    proxy.dead = True
    questions: list[str] = []

    def ask(problem: str) -> bool:
        questions.append(problem)
        return True

    with storage.database() as engine:
        crawl_id = register_crawl(engine, f"{upstream}/a", "polygon", Settings(crawl=_crawl(proxy, max_urls=3)))
        result = run_crawl(engine, crawl_id, ask=ask)
        assert result.status == "finished" and result.proxy_down and "407" in result.proxy_down
        assert _pages(engine, crawl_id)[f"{upstream}/a"][0] == 200
    assert len(questions) == 1 and "127.0.0.1" in questions[0]
    assert proxy.seen == []  # nothing got through it


def test_proxy_dying_mid_crawl_stops_it_and_resume_loses_nothing(proxy: polygon.Proxy) -> None:
    settings = Settings(crawl=_crawl(proxy, max_urls=40, concurrency=2, proxy_max_failures=3))
    with storage.database() as engine:
        crawl_id = register_crawl(engine, f"{proxy.base()}/", "polygon", settings)
        proxy.die_after = 10
        with pytest.raises(ProxyUnavailable, match="proxy errors in a row"):
            run_crawl(engine, crawl_id)
        stopped = _pages(engine, crawl_id)
        assert _status(engine, crawl_id) == "interrupted"
        assert stopped and not _proxy_errors(proxy, stopped)
        proxy.die_after, proxy.dead = None, False
        assert run_crawl(engine, crawl_id).status == "finished"
        pages = _pages(engine, crawl_id)
    assert len(pages) > len(stopped)
    assert not _proxy_errors(proxy, pages)


def test_with_fallback_direct_a_dying_proxy_is_dropped_and_its_urls_fetched_again(
    proxy: polygon.Proxy, upstream: str
) -> None:
    crawl = _crawl(proxy, max_urls=30, concurrency=2, proxy_max_failures=3, proxy_fallback="direct")
    proxy.die_after = 8
    with storage.database() as engine:
        result = crawl_site(engine, f"{upstream}/", "polygon", Settings(crawl=crawl))
        pages = _pages(engine, result.crawl_id)
    assert result.status == "finished" and result.proxy_down and "in a row" in result.proxy_down
    assert not _proxy_errors(proxy, pages, upstream)


def test_fetch_checks_the_proxy_first(proxy: polygon.Proxy, upstream: str) -> None:
    proxy.dead = True
    with pytest.raises(ProxyUnavailable):
        fetch(f"{proxy.base()}/a", CrawlSettings(proxy_urls=[proxy.url]))
    page = fetch(f"{upstream}/a", CrawlSettings(proxy_urls=[proxy.url], proxy_fallback="direct"))
    assert page.status == 200


def test_robots_test_reads_robots_txt_through_the_proxy(proxy: polygon.Proxy) -> None:
    from rb_spider.core.crawl import test_robots

    rows = test_robots(CrawlSettings(proxy_urls=[proxy.url]), [f"{proxy.base()}/private/x"])
    assert rows[0]["allowed"] is False and ("", "/robots.txt") in [("", path) for _, path in proxy.seen]


def test_cli_without_a_terminal_follows_the_key_and_exits_5(proxy: polygon.Proxy) -> None:
    import json

    from typer.testing import CliRunner

    from rb_spider.cli import app

    proxy.dead = True
    result = CliRunner().invoke(
        app, ["--json", "fetch", f"{proxy.base()}/a", "--set", f"crawl.proxy_urls=['{proxy.url}']"]
    )
    assert result.exit_code == 5  # no one to ask: crawl.proxy_fallback = stop
    assert json.loads(result.stdout)["error"]["code"] == "PROXY_UNAVAILABLE"


# --- failover: a mobile proxy's two doors -----------------------------------------------------------------


@pytest.fixture
def backup(upstream: str):
    with polygon.proxy(upstream) as found:
        yield found


def test_failover_starts_on_the_backup_when_the_first_is_dead(proxy: polygon.Proxy, backup: polygon.Proxy) -> None:
    proxy.dead = True
    crawl = CrawlSettings(proxy_urls=[proxy.url, backup.url], proxy_mode="failover", max_urls=10)
    with storage.database() as engine:
        result = crawl_site(engine, f"{proxy.base()}/", "polygon", Settings(crawl=crawl))
        pages = _pages(engine, result.crawl_id)
    assert result.status == "finished" and result.proxy_down is None
    assert pages[f"{proxy.base()}/"][0] == 200 and backup.seen and not _proxy_errors(proxy, pages)


def test_failover_switches_mid_crawl_and_loses_nothing(proxy: polygon.Proxy, backup: polygon.Proxy) -> None:
    proxy.die_after = 8
    crawl = CrawlSettings(proxy_urls=[proxy.url, backup.url], proxy_mode="failover", max_urls=30, concurrency=2,
                          proxy_max_failures=3)  # fmt: skip
    with storage.database() as engine:
        result = crawl_site(engine, f"{proxy.base()}/", "polygon", Settings(crawl=crawl))
        pages = _pages(engine, result.crawl_id)
    assert result.status == "finished" and result.proxy_down is None
    assert len(backup.seen) > 1 and not _proxy_errors(proxy, pages)


# --- a new IP when the site blocks --------------------------------------------------------------------------


@pytest.fixture
def changing(proxy: polygon.Proxy, monkeypatch) -> polygon.Proxy:
    monkeypatch.setenv("SPIDER_PROXY_KEY_API_KEY", polygon.Proxy.KEY)
    return proxy


def _changing(proxy: polygon.Proxy, **crawl) -> CrawlSettings:
    dead_link = "http://127.0.0.1:1/changeip?proxy_key={key}"  # the first link is down: the next one is tried
    return _crawl(proxy, proxy_change_ip_urls=[dead_link, proxy.change_url], proxy_change_ip_min_interval_s=0,
                  proxy_change_ip_wait_s=5, **crawl)  # fmt: skip


def test_a_blocked_site_gets_a_new_ip_and_every_page_is_fetched(changing: polygon.Proxy) -> None:
    changing.blocks_after = 6
    with storage.database() as engine:
        result = crawl_site(engine, f"{changing.base()}/", "polygon", Settings(crawl=_changing(changing, max_urls=40)))
        pages = _pages(engine, result.crawl_id)
    assert result.status == "finished" and changing.changes >= 3
    assert not [url for url, (status, _) in pages.items() if status == 403]  # the polygon itself never answers 403


def test_when_every_new_ip_is_blocked_it_gives_up_and_stores_the_blocks(changing: polygon.Proxy) -> None:
    changing.blocks_after, changing.change_helps = 1, False
    with storage.database() as engine:
        result = crawl_site(engine, f"{changing.base()}/", "polygon", Settings(crawl=_changing(changing, max_urls=10)))
        pages = _pages(engine, result.crawl_id)
    assert result.status == "finished"
    assert changing.changes == 3  # UNPRODUCTIVE_CHANGES: three new IPs blocked at once, then no more
    assert any(status == 403 for status, _ in pages.values())


def test_fetch_changes_the_ip_too(changing: polygon.Proxy) -> None:
    changing.blocks_after = 1
    changing.burn()  # the site has seen enough of this IP
    page = fetch(f"{changing.base()}/a", _changing(changing))
    assert page.status == 200 and changing.changes == 1


def test_the_change_ip_key_is_asked_for_before_the_crawl(proxy: polygon.Proxy, monkeypatch) -> None:
    from rb_spider.core.errors import AuthRequired

    monkeypatch.delenv("SPIDER_PROXY_KEY_API_KEY", raising=False)
    monkeypatch.setattr(
        "rb_spider.providers.secrets.password", lambda name: polygon.Proxy.PASSWORD if name == "proxy" else None
    )
    with storage.database() as engine, pytest.raises(AuthRequired, match="proxy_key"):
        register_crawl(engine, f"{proxy.base()}/", "polygon", Settings(crawl=_changing(proxy)))


def test_a_socks5_door_is_handed_out_as_is() -> None:
    import asyncio

    from rb_spider.core.proxy import Proxies

    proxies = Proxies(["http://u:p@a.example:8000", "socks5h://u:p%40x@b.example:1080"], "failover")
    proxies.current = 1  # Crawlee's own configuration would refuse this address: http(s) only
    info = asyncio.run(proxies.new_proxy_info(None, None, None))
    assert info and (info.scheme, info.hostname, info.port, info.password) == ("socks5h", "b.example", 1080, "p@x")


# --- a dead proxy found in seconds: a TCP check, the proxy against a direct request, the breaker -------------

FAST: dict[str, Any] = {
    "timeout_s": 1,
    "proxy_connect_timeout_s": 0.5,
}  # the bounds below: seconds of these, not minutes


def _timed(run):
    started = time.monotonic()
    result = run()
    return result, time.monotonic() - started


@pytest.fixture
def unreachable(monkeypatch) -> Iterator[str]:
    monkeypatch.setenv("SPIDER_PROXY_API_KEY", polygon.Proxy.PASSWORD)
    with polygon.unreachable_proxy() as url:
        yield url


def test_cli_a_proxy_that_hangs_on_connect_exits_5_within_the_connect_timeout(unreachable: str, upstream: str) -> None:
    from typer.testing import CliRunner

    from rb_spider.cli import app

    urls = [f"{upstream}/a", f"{upstream}/b", f"{upstream}/c"]
    keys = [f"crawl.proxy_urls=['{unreachable}']", "crawl.proxy_connect_timeout_s=0.5", "crawl.timeout_s=5"]
    command = ["--json", "fetch", *urls, *[arg for key in keys for arg in ("--set", key)]]
    result, elapsed = _timed(lambda: CliRunner().invoke(app, command))
    assert result.exit_code == 5  # no terminal: crawl.proxy_fallback = stop
    assert json.loads(result.stdout)["error"]["code"] == "PROXY_UNAVAILABLE"
    assert elapsed < 0.5 + 2.5  # the connect timeout and a margin, not 3 x crawl.timeout_s = 15 s


def test_with_fallback_direct_a_proxy_that_hangs_on_connect_costs_one_check(unreachable: str, upstream: str) -> None:
    settings = CrawlSettings(proxy_urls=[unreachable], proxy_fallback="direct", proxy_connect_timeout_s=0.5,
                             timeout_s=5)  # fmt: skip
    urls = [f"{upstream}/a", f"{upstream}/b", f"{upstream}/c"]
    pages, elapsed = _timed(lambda: list(fetch_many(urls, settings)))
    assert [page.status for page in pages] == [200, 200, 200]
    assert elapsed < 0.5 + 2.5


@pytest.mark.parametrize("failure", ["hangs", "refuses", "407"])
def test_a_dead_proxy_is_found_before_the_first_url_in_seconds(proxy: polygon.Proxy, upstream: str, failure) -> None:
    url = polygon.refusing_proxy() if failure == "refuses" else proxy.url
    proxy.hangs, proxy.dead = failure == "hangs", failure == "407"
    settings = CrawlSettings(proxy_urls=[url], **FAST)
    with pytest.raises(ProxyUnavailable) as stopped:
        started = time.monotonic()
        fetch(f"{upstream}/a", settings)
    assert time.monotonic() - started < 1 + 2  # one check: at most min(crawl.timeout_s, 10), and a margin
    assert "127.0.0.1" in str(stopped.value)
    page = fetch(f"{upstream}/a", settings.model_copy(update={"proxy_fallback": "direct"}))
    assert page.status == 200 and page.error is None


def test_a_site_down_for_everyone_does_not_blame_a_working_proxy(monkeypatch) -> None:
    monkeypatch.setenv("SPIDER_PROXY_API_KEY", polygon.Proxy.PASSWORD)
    with polygon.silent_site() as down, polygon.proxy(down) as proxy:
        urls = [f"{proxy.base()}/a", f"{proxy.base()}/b", f"{proxy.base()}/c", f"{proxy.base()}/d"]
        pages = list(fetch_many(urls, CrawlSettings(proxy_urls=[proxy.url], **FAST), concurrency=1))
    assert [page.status for page in pages] == [None] * 4  # each URL has its own error, the run went on
    assert all(page.error and "Timeout" in page.error for page in pages)


def test_fetch_drops_a_proxy_that_stops_answering_mid_run(proxy: polygon.Proxy, upstream: str) -> None:
    proxy.hang_after = 2  # robots.txt of the check and the first page come through, then nothing
    urls = [f"{upstream}/a?n={n}" for n in range(12)]
    settings = CrawlSettings(proxy_urls=[proxy.url], **FAST)
    with pytest.raises(ProxyUnavailable, match="in a row") as stopped:
        started = time.monotonic()
        list(fetch_many(urls, settings, concurrency=1))
    # three URLs without an answer, then one check: not 11 x crawl.timeout_s
    assert time.monotonic() - started < 3 * 1 + 1 + 3
    assert "127.0.0.1" in str(stopped.value)
    proxy.hangs, proxy.hang_after = False, 2
    proxy.seen.clear()
    pages = list(fetch_many(urls, settings.model_copy(update={"proxy_fallback": "direct"}), concurrency=1))
    assert pages[-1].status == 200 and pages[-1].error is None  # on without the proxy, the site sees this IP


def test_crawl_checks_a_proxy_that_stops_answering_and_stops(proxy: polygon.Proxy, upstream: str) -> None:
    crawl = _crawl(proxy, max_urls=30, concurrency=2, **FAST)
    with storage.database() as engine:
        crawl_id = register_crawl(engine, f"{upstream}/", "polygon", Settings(crawl=crawl))
        proxy.hang_after = 6
        with pytest.raises(ProxyUnavailable, match="in a row") as stopped_by:
            started = time.monotonic()
            run_crawl(engine, crawl_id)
        # three requests without an answer (each tried twice), one check: not every URL's timeouts
        assert time.monotonic() - started < 3 * 2 * 1 + 1 + 4
        assert stopped_by.value.exit_code == 5  # spider crawl: PROXY_UNAVAILABLE, no result JSON
        assert _status(engine, crawl_id) == "interrupted"  # resumable
        stopped = _pages(engine, crawl_id)
        assert not [url for url, (_, error) in stopped.items() if error and "Timeout" in error]
        proxy.hangs, proxy.hang_after = False, None  # the modem is back: the crawl goes on where it stopped
        assert run_crawl(engine, crawl_id).status == "finished"
        pages = _pages(engine, crawl_id)
    assert len(pages) > len(stopped)
    assert not [url for url, (_, error) in pages.items() if error and "Timeout" in error]


def test_crawl_with_fallback_direct_goes_on_without_a_proxy_that_stops_answering(
    proxy: polygon.Proxy, upstream: str
) -> None:
    crawl = _crawl(proxy, max_urls=30, concurrency=2, proxy_fallback="direct", **FAST)
    proxy.hang_after = 6
    with storage.database() as engine:
        result = crawl_site(engine, f"{upstream}/", "polygon", Settings(crawl=crawl))
        pages = _pages(engine, result.crawl_id)
    assert result.status == "finished" and result.proxy_down and "in a row" in result.proxy_down
    assert not [url for url, (_, error) in pages.items() if url.startswith(upstream) and error and "Timeout" in error]


def test_a_dead_proxy_gets_one_ip_change_and_the_providers_refusal_is_in_the_error(
    proxy: polygon.Proxy, monkeypatch
) -> None:
    monkeypatch.setenv("SPIDER_PROXY_KEY_API_KEY", "wrong-key-7f3a")
    proxy.dead = True
    with pytest.raises(ProxyUnavailable) as stopped:
        fetch(f"{proxy.base()}/a", _changing(proxy, **FAST))
    assert proxy.change_asks == 1  # one call to the provider, then the check again
    assert "bad key" in str(stopped.value) and "407" in str(stopped.value)
    assert "wrong-key-7f3a" not in str(stopped.value)


def test_an_answer_sent_before_a_miss_does_not_clear_the_proxy() -> None:
    """IDEA-365: a slow answer that left before the proxy died stored the pages it failed meanwhile as errors."""
    import asyncio

    from rb_spider.core.proxy import Breaker

    breaker = Breaker(CrawlSettings(proxy_max_failures=3), client=None)  # ty: ignore[invalid-argument-type]
    sent_before = time.monotonic()
    assert asyncio.run(breaker.missed("http://site.test/a", "http://127.0.0.1:1")) == (None, [])
    breaker.hold("page a")
    assert breaker.answered(sent_before) == []  # on its way before the miss: says nothing of the proxy now
    assert breaker.answered(time.monotonic()) == ["page a"]  # sent after it: the proxy works, the page is the site's
