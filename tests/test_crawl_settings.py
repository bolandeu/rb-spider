"""crawl.* settings (issue #7): each one observed on the polygon, or unit-tested where a live site can't show it."""

from __future__ import annotations

import asyncio
import json

import pytest
import sqlalchemy as sa
from crawlee._utils.robots import RobotsTxtFile
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import crawl as crawl_service
from rb_spider.core import storage
from rb_spider.core.crawl import Scope, crawl_site, proxy_urls, requests_per_minute
from rb_spider.core.errors import AuthRequired
from rb_spider.core.extract import parse_page
from rb_spider.core.settings import USER_AGENT_PRESETS, CrawlSettings, Settings

from . import polygon


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


def _crawl(base_url: str, start: str = "/", **crawl) -> dict[str, dict]:
    """Crawl the polygon with these crawl.* settings; url path -> stored page row."""
    with storage.database() as engine:
        result = crawl_site(engine, f"{base_url}{start}", "polygon", Settings(crawl=CrawlSettings(**crawl)))
        with engine.connect() as conn:
            rows = conn.execute(sa.select(storage.pages).where(storage.pages.c.crawl_id == result.crawl_id)).mappings()
            return {row["url"].removeprefix(base_url): dict(row) for row in rows}


def test_include_and_exclude(base_url: str) -> None:
    pages = _crawl(base_url, include=["/(a|c)$"], exclude=["/c$"])
    assert set(pages) == {"/", "/a"}  # the start URL is always crawled; exclude beats include


def test_max_depth(base_url: str) -> None:
    pages = _crawl(base_url, max_depth=1)
    assert "/a" in pages
    assert "/c" not in pages  # / → /a → /c is depth 2
    assert max(p["depth"] for p in pages.values()) == 1


def test_max_links_per_page(base_url: str) -> None:
    pages = _crawl(base_url, max_links_per_page=2)
    assert set(pages) == {"/", "/a", "/b", "/c"}  # home's first two links, then their own (/a → /c, /b → /)


def test_stay_in_start_folder(base_url: str) -> None:
    pages = _crawl(base_url, "/shop/", stay_in_start_folder=True)
    assert {path for path, p in pages.items() if p["parsed"]} == {"/shop/", "/shop/item"}
    assert pages["/a"]["parsed"] is False  # outside the folder: checked (status), not crawled
    assert pages["/a"]["status_code"] == 200
    folder_only = _crawl(base_url, "/shop/", stay_in_start_folder=True, check_outside_start_folder=False)
    assert set(folder_only) == {"/shop/", "/shop/item"}
    assert "/a" in _crawl(base_url, "/shop/")  # by default the whole site


def test_headers_and_user_agent_preset_reach_the_server(base_url: str) -> None:
    polygon.SEEN_HEADERS.clear()
    _crawl(base_url, max_urls=2, user_agent="yandexbot", headers={"Accept-Language": "ru", "X-Audit": "spider"})
    sent = [h for h in polygon.SEEN_HEADERS if h.get("x-audit") == "spider"]
    assert sent
    assert all(h["user-agent"] == USER_AGENT_PRESETS["yandexbot"] and h["accept-language"] == "ru" for h in sent)


def test_robots_group_follows_the_user_agent(base_url: str) -> None:
    assert _crawl(base_url)["/g-blocked"]["status_code"] == 200  # the * group allows it
    as_googlebot = _crawl(base_url, user_agent="googlebot")
    assert as_googlebot["/g-blocked"]["blocked"] == "robots_txt"
    assert as_googlebot["/g-blocked"]["status_code"] == 0  # respect: not fetched
    assert _crawl(base_url, robots_user_agent="Googlebot")["/g-blocked"]["blocked"] == "robots_txt"


def test_robots_ignore_and_report(base_url: str) -> None:
    ignored = _crawl(base_url, robots="ignore")["/private/secret"]
    assert (ignored["status_code"], ignored["blocked"]) == (200, None)
    reported = _crawl(base_url, robots="report")["/private/secret"]
    assert (reported["status_code"], reported["blocked"]) == (200, "robots_txt")  # fetched, flagged
    assert reported["indexability_status"] == "Blocked by Robots.txt"


def test_timeout_turns_a_slow_url_into_no_response(base_url: str) -> None:
    page = _crawl(base_url, "/slow", timeout_s=0.5)["/slow"]
    assert page["status_code"] == 0
    assert page["error"]


def test_content_exclude_leaves_menus_out_of_the_word_count() -> None:
    html = b"<html><body><nav>" + b"menu " * 50 + b"</nav><p>one two three</p><footer>foot</footer></body></html>"
    headers = {"content-type": "text/html"}
    assert parse_page("https://s.ex/", 200, headers, html).onpage["word_count"] == 3
    assert parse_page("https://s.ex/", 200, headers, html, content_exclude=[]).onpage["word_count"] == 54


def test_scope_subdomains_and_url_length() -> None:
    site = Scope("https://www.site.ru/", CrawlSettings())
    assert site.internal("https://www.site.ru/x")
    assert not site.internal("https://blog.site.ru/x")
    everything = Scope("https://www.site.ru/", CrawlSettings(all_subdomains=True, max_url_length=30))
    assert everything.internal("https://blog.site.ru/x") and everything.internal("https://site.ru/")
    assert not everything.internal("https://othersite.ru/")
    assert not everything.crawlable("https://site.ru/" + "x" * 30)


def test_rate_cap_from_max_rps_and_crawl_delay() -> None:
    assert requests_per_minute(CrawlSettings(), None) == float("inf")
    assert requests_per_minute(CrawlSettings(max_rps=5), None) == 300
    assert requests_per_minute(CrawlSettings(max_rps=5), 2) == 30  # Crawl-delay 2 s is stricter
    robots = asyncio.run(RobotsTxtFile.from_content("https://s.ex/robots.txt", "User-agent: *\nCrawl-delay: 3\n"))
    assert robots.get_crawl_delay("Mozilla/5.0") == 3


def test_proxy_password_comes_from_the_keychain(monkeypatch) -> None:
    settings = CrawlSettings(proxy_urls=["http://user:{password}@proxy.example:8000", "http://open.example:3128"])
    monkeypatch.setattr(crawl_service.credentials, "get_secret", lambda provider: None)
    with pytest.raises(AuthRequired):
        proxy_urls(settings)
    monkeypatch.setattr(crawl_service.credentials, "get_secret", lambda provider: "s3cret")
    assert proxy_urls(settings) == ["http://user:s3cret@proxy.example:8000", "http://open.example:3128"]


def test_cli_flags(base_url: str) -> None:
    result = CliRunner().invoke(
        app, ["--json", "crawl", f"{base_url}/", "--max-depth", "0", "--user-agent", "bingbot", "--ignore-robots"]
    )
    assert result.exit_code == 0, result.output
    shown = json.loads(CliRunner().invoke(app, ["--json", "crawls", "show"]).stdout)["settings"]["crawl"]
    assert (shown["max_depth"], shown["user_agent"], shown["robots"]) == (0, "bingbot", "ignore")


def test_doctor_asks_for_the_proxy_password_only_when_needed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(crawl_service.credentials, "get_credential", lambda provider: None)
    doctor = lambda: json.loads(CliRunner().invoke(app, ["--project", str(tmp_path), "--json", "doctor"]).stdout)  # noqa: E731
    assert not [c for c in doctor()["checks"] if c["name"].startswith("credential:")]
    CliRunner().invoke(app, ["--project", str(tmp_path), "init"])
    CliRunner().invoke(
        app, ["--project", str(tmp_path), "config", "set", "crawl.proxy_urls", '["http://u:{password}@p:1"]']
    )
    [check] = [c for c in doctor()["checks"] if c["name"] == "credential:proxy"]
    assert check["ok"] is False
