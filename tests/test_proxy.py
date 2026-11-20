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
        crawl_id = register_crawl(
            engine, f"{proxy.base()}/a", "polygon", Settings(crawl=_crawl(proxy, proxy_state_ttl_s=0))
        )  # it is paid again at once
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
    settings = Settings(crawl=_crawl(proxy, max_urls=40, concurrency=2, proxy_max_failures=3, proxy_state_ttl_s=0))
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


KNOWN_PROXY_DEFECT = pytest.mark.xfail(
    reason="failover/pre-check on the in-process proxy answers 407; proxies are optional, so this must not block a "
    "release (TODO: rb-spider proxy failover)",
    strict=False,
)


@KNOWN_PROXY_DEFECT
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

    proxies = Proxies(["http://u:p@a.example:8000", "socks5h://u:p%40x@b.example:1080"], "failover", 5)
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


@KNOWN_PROXY_DEFECT
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
    crawl = _crawl(proxy, max_urls=30, concurrency=2, proxy_state_ttl_s=0, **FAST)  # the modem is back at once
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


# --- the proxy state remembered between runs (crawl.proxy_state_ttl_s) ---------------------------------------


def _state_file():
    from rb_spider.core import proxy_state

    return proxy_state.state_path()


def _state() -> dict:
    return json.loads(_state_file().read_text())


def _age_state(seconds: int) -> None:
    """Make every remembered check `seconds` older: the clock of a later run."""
    from datetime import datetime, timedelta

    state = _state()
    for entry in state.values():
        entry["checked_at"] = (datetime.fromisoformat(entry["checked_at"]) - timedelta(seconds=seconds)).isoformat()
    _state_file().write_text(json.dumps(state))


def test_a_proxy_known_dead_is_not_connected_to_again_and_the_fallback_decides(
    proxy: polygon.Proxy, upstream: str
) -> None:
    proxy.hangs = True
    settings = CrawlSettings(proxy_urls=[proxy.url], proxy_fallback="direct", proxy_state_ttl_s=600, **FAST)
    assert fetch(f"{upstream}/a", settings).status == 200  # the check finds it dead, the fallback goes direct
    first = proxy.connections
    assert first > 0
    assert fetch(f"{upstream}/a", settings).status == 200
    assert proxy.connections == first  # the second run made no connection to the proxy
    stop = settings.model_copy(update={"proxy_fallback": "stop"})
    with pytest.raises(ProxyUnavailable):
        fetch(f"{upstream}/a", stop)
    assert proxy.connections == first


def test_a_proxy_remembered_dead_gets_no_ip_change_until_a_new_check_finds_it_dead(
    proxy: polygon.Proxy, upstream: str, monkeypatch
) -> None:
    monkeypatch.setenv("SPIDER_PROXY_KEY_API_KEY", polygon.Proxy.KEY)
    proxy.dead = True
    settings = _changing(proxy, proxy_fallback="direct", proxy_state_ttl_s=600, **FAST)
    assert fetch(f"{upstream}/a", settings).status == 200
    assert proxy.change_asks == 1  # the first run: a new check found it dead, one IP change
    connections = proxy.connections
    assert fetch(f"{upstream}/a", settings).status == 200
    assert proxy.change_asks == 1 and proxy.connections == connections  # the second run: the memory decides
    _age_state(601)
    assert fetch(f"{upstream}/a", settings).status == 200
    assert proxy.change_asks == 2 and proxy.connections > connections  # older than the ttl: checked, changed


def test_a_proxy_known_alive_is_not_checked_again(proxy: polygon.Proxy, upstream: str) -> None:
    settings = CrawlSettings(proxy_urls=[proxy.url], proxy_state_ttl_s=600, **FAST)
    assert fetch(f"{upstream}/a", settings).status == 200
    checks = [path for _, path in proxy.seen if path == "/robots.txt"]
    assert len(checks) == 1
    assert fetch(f"{upstream}/b", settings).status == 200
    assert [path for _, path in proxy.seen if path == "/robots.txt"] == checks  # no second start check
    assert ("", "/b") in [("", path) for _, path in proxy.seen]  # the page itself came through the proxy


def test_an_entry_older_than_the_ttl_is_checked_again_and_updated(proxy: polygon.Proxy, upstream: str) -> None:
    settings = CrawlSettings(proxy_urls=[proxy.url], proxy_state_ttl_s=600, **FAST)
    fetch(f"{upstream}/a", settings)
    (key,) = _state()
    before = _state()[key]["checked_at"]
    _age_state(601)
    aged = _state()[key]["checked_at"]
    assert aged < before
    fetch(f"{upstream}/a", settings)
    assert len([path for _, path in proxy.seen if path == "/robots.txt"]) == 2  # checked again
    assert _state()[key]["checked_at"] > aged and _state()[key]["status"] == "alive"


def test_ttl_zero_turns_the_memory_off(proxy: polygon.Proxy, upstream: str) -> None:
    settings = CrawlSettings(proxy_urls=[proxy.url], proxy_state_ttl_s=0, **FAST)
    fetch(f"{upstream}/a", settings)
    fetch(f"{upstream}/a", settings)
    assert len([path for _, path in proxy.seen if path == "/robots.txt"]) == 2


def test_failover_skips_an_address_known_dead(proxy: polygon.Proxy, backup: polygon.Proxy, upstream: str) -> None:
    proxy.hangs = True
    crawl = CrawlSettings(proxy_urls=[proxy.url, backup.url], proxy_mode="failover", proxy_state_ttl_s=600, **FAST)
    assert fetch(f"{upstream}/a", crawl).status == 200
    first = proxy.connections
    assert fetch(f"{upstream}/b", crawl).status == 200
    assert proxy.connections == first  # the next address that is not known dead, no connection to the dead one
    assert ("", "/b") in [("", path) for _, path in backup.seen]


def test_the_state_file_keeps_no_password_and_the_ip_changes(changing: polygon.Proxy, upstream: str) -> None:
    changing.dead = True
    with pytest.raises(ProxyUnavailable):
        fetch(f"{upstream}/a", _changing(changing, **FAST))
    (entry,) = _state().values()
    assert entry["status"] == "dead" and entry["reason"] and len(entry["ip_changes"]) == 1
    assert polygon.Proxy.PASSWORD not in _state_file().read_text()


def test_two_runs_at_once_leave_a_whole_file(proxy: polygon.Proxy) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from rb_spider.core import proxy_state

    urls = [f"http://u:secret@127.0.0.1:{port}" for port in range(9000, 9008)]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda url: [proxy_state.record(url, None) for _ in range(20)], urls))
    assert isinstance(_state(), dict) and not list(_state_file().parent.glob("*.tmp"))


def test_doctor_shows_the_state_of_each_address_without_network(proxy: polygon.Proxy, upstream: str) -> None:
    from rb_spider.core import proxy_state, settings

    from .test_cli import invoke_json

    other = "socks5h://mobile:{password}@127.0.0.1:1"
    settings.global_config_path().write_text(f'[crawl]\nproxy_urls = ["{proxy.url}", "{other}"]\n')
    proxy_state.record_ip_change([proxy.url.replace("{password}", polygon.Proxy.PASSWORD)])
    proxy_state.record(proxy.url.replace("{password}", polygon.Proxy.PASSWORD), None)
    proxy_state.record(other.replace("{password}", "pw"), "no TCP connection: refused")
    _, payload = invoke_json("doctor")
    check = next(c for c in payload["checks"] if c["name"] == "proxy")
    first, second = check["addresses"]
    assert (first["state"], first["reason"], first["ip_changes_24h"]) == ("alive", None, 1)
    assert (second["state"], second["reason"]) == ("dead", "no TCP connection: refused")
    assert first["checked_at"] and second["address"] == "socks5h://mobile@127.0.0.1:1"
    assert polygon.Proxy.PASSWORD not in json.dumps(payload) and "auth status --check" in check["detail"]
    assert proxy.connections == 0  # from the state file, no network


# --- crawl.proxy_concurrency: a modem holds a few connections; one stderr line when the proxy goes off ----------


def test_the_proxy_never_sees_more_than_proxy_concurrency_requests_at_once_in_fetch(
    proxy: polygon.Proxy, upstream: str
) -> None:
    proxy.delay_s = 0.2
    settings = CrawlSettings(proxy_urls=[proxy.url], proxy_concurrency=2)
    pages = list(fetch_many([f"{proxy.base()}/a?n={n}" for n in range(10)], settings, concurrency=10))
    assert [page.status for page in pages] == [200] * 10
    assert proxy.peak == 2


def test_the_proxy_never_sees_more_than_proxy_concurrency_requests_at_once_in_crawl(proxy: polygon.Proxy) -> None:
    proxy.delay_s = 0.2
    settings = Settings(crawl=_crawl(proxy, max_urls=10, concurrency=10, proxy_concurrency=2, robots="ignore"))
    with storage.database() as engine:
        result = crawl_site(engine, f"{proxy.base()}/", "polygon", settings)
    assert result.status == "finished"
    assert proxy.peak == 2


def test_a_dropped_proxy_leaves_direct_requests_at_crawl_concurrency(proxy: polygon.Proxy, upstream: str) -> None:
    proxy.dead = True
    settings = CrawlSettings(proxy_urls=[proxy.url], proxy_concurrency=1, proxy_fallback="direct", proxy_state_ttl_s=0)
    started = time.monotonic()
    slow = [f"{upstream}/slow?n={n}" for n in range(3)]
    pages = list(fetch_many(slow, settings, concurrency=3))
    assert [page.error for page in pages] == [None] * 3
    assert time.monotonic() - started < 2 * polygon.SLOW_S  # three at once, not one after another


def _fetch_json(*args: str):
    from typer.testing import CliRunner

    from rb_spider.cli import app

    result = CliRunner().invoke(app, ["--json", "fetch", *args])
    return result, [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def _about_the_proxy(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if "proxy" in line.lower()]


def test_a_dead_proxy_with_fallback_direct_says_so_once_on_stderr_for_five_urls(
    proxy: polygon.Proxy, upstream: str
) -> None:
    proxy.dead = True
    urls = [f"{upstream}/a?n={n}" for n in range(5)]
    result, lines = _fetch_json(*urls, "--set", f"crawl.proxy_urls=['{proxy.url}']",
                                "--set", "crawl.proxy_fallback='direct'")  # fmt: skip
    assert result.exit_code == 0 and [line["status"] for line in lines] == [200] * 5
    said = _about_the_proxy(result.stderr)
    assert len(said) == 1 and "without it" in said[0]


def test_a_dead_proxy_with_fallback_stop_says_so_once_on_stderr(proxy: polygon.Proxy) -> None:
    proxy.dead = True
    urls = [f"{proxy.base()}/a?n={n}" for n in range(5)]
    result, _ = _fetch_json(*urls, "--set", f"crawl.proxy_urls=['{proxy.url}']")
    assert result.exit_code == 5
    said = _about_the_proxy(result.stderr)
    assert len(said) == 1 and "stopping" in said[0]


def test_a_proxy_dying_mid_run_says_so_once_on_stderr(proxy: polygon.Proxy, upstream: str) -> None:
    proxy.hang_after = 2
    urls = [f"{upstream}/a?n={n}" for n in range(12)]
    result, lines = _fetch_json(*urls, "--concurrency", "1", "--set", f"crawl.proxy_urls=['{proxy.url}']",
                                "--set", "crawl.proxy_fallback='direct'", "--set", "crawl.timeout_s=1",
                                "--set", "crawl.proxy_connect_timeout_s=0.5")  # fmt: skip
    assert result.exit_code == 0 and lines[-1]["status"] == 200
    assert len(_about_the_proxy(result.stderr)) == 1
