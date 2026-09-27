"""crawl.* settings (issue #7): each one observed on the polygon, or unit-tested where a live site can't show it."""

from __future__ import annotations

import asyncio
import importlib.util
import json

import pytest
import sqlalchemy as sa
from crawlee._utils.robots import RobotsTxtFile
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import crawl as crawl_service
from rb_spider.core import storage
from rb_spider.core.crawl import crawl_site, proxy_urls, requests_per_minute
from rb_spider.core.errors import AuthRequired
from rb_spider.core.extract import parse_page
from rb_spider.core.scope import Rewriter, Scope
from rb_spider.core.settings import (
    USER_AGENT_PRESETS,
    CollectSettings,
    CrawlSettings,
    RewriteSettings,
    Settings,
    ThresholdSettings,
)

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


@pytest.mark.skipif(importlib.util.find_spec("curl_cffi") is None, reason="the `curl` extra is not installed")
def test_curl_http_client_crawls_with_every_redirect_step(base_url: str) -> None:
    from rb_spider.fetch import fetch

    with storage.database() as engine:
        result = crawl_site(engine, f"{base_url}/", "polygon", Settings(crawl=CrawlSettings(http_client="curl")))
        with engine.connect() as conn:
            rows = dict(conn.execute(sa.select(storage.pages.c.url, storage.pages.c.status_code)
                                     .where(storage.pages.c.crawl_id == result.crawl_id)).all())  # fmt: skip
    assert rows[f"{base_url}/chain1"] == 301 and rows[f"{base_url}/chain2"] == 302 and rows[f"{base_url}/a"] == 200
    page = fetch(f"{base_url}/old", CrawlSettings(http_client="curl"))
    assert page.final_url == f"{base_url}/a" and page.redirects[0]["status"] == 301


def test_curl_http_client_without_its_extra(monkeypatch) -> None:
    from rb_spider.core.crawl import http_client
    from rb_spider.core.errors import HttpClientUnavailable

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "curl_cffi" else real(name, *a))
    with pytest.raises(HttpClientUnavailable):
        http_client(CrawlSettings(http_client="curl"))


# --- rewrite.* (#26) ----------------------------------------------------------------


def _crawl_rewritten(base_url: str, **rewrite) -> dict[str, dict]:
    with storage.database() as engine:
        result = crawl_site(engine, f"{base_url}/", "polygon", Settings(rewrite=RewriteSettings(**rewrite)))
        with engine.connect() as conn:
            rows = conn.execute(sa.select(storage.pages).where(storage.pages.c.crawl_id == result.crawl_id)).mappings()
            return {row["url"].removeprefix(base_url): dict(row) for row in rows}


def test_rewrite_remove_params(base_url: str) -> None:
    pages = _crawl_rewritten(base_url, remove_params=["sort", "utm_source"])
    assert "/b?sort=price" not in pages  # became /b, already crawled
    assert "/u/landing" in pages
    assert "/u/landing?utm_source=news" not in pages
    assert "/search?q=test" in pages  # other parameters stay


def test_rewrite_regex_and_lowercase(base_url: str) -> None:
    pages = _crawl_rewritten(base_url, regex=[("/old$", "/a"), (r"/shoes/shoes$", r"/c")], lowercase=True)
    assert "/old" not in pages and "/u/shoes/shoes" not in pages
    assert "/u/UPPER" not in pages
    assert pages["/u/upper"]["status_code"] == 404  # the lower-case address doesn't exist on the polygon


def test_rewriter_percent_encoding_and_order() -> None:
    rewrite = Rewriter(
        RewriteSettings(remove_params=["sid"], regex=[("^http://", "https://")], percent_encoding="upper")
    )
    assert rewrite("http://s.example/%d0%b0?sid=1&page=2#x") == "https://s.example/%D0%B0?page=2"
    assert Rewriter(RewriteSettings(percent_encoding="lower"))("https://s.example/%D0%B0") == "https://s.example/%d0%b0"
    assert not Rewriter(None).active


def test_rewrite_regex_is_validated() -> None:
    with pytest.raises(ValueError, match="invalid regular expression"):
        RewriteSettings(regex=[("(", "x")])


# --- limits and advanced settings (#35) -----------------------------------------------------------


def _pages_of(base_url: str, start: str = "/", **crawl) -> dict[str, dict]:
    return _crawl(base_url, start, **crawl)


def test_folder_depth_and_query_limits(base_url: str) -> None:
    pages = _pages_of(base_url, max_folder_depth=1, max_query_params=0)
    assert "/a" in pages and "/shop/" in pages  # one folder level: /shop/ is /shop
    assert "/shop/item" not in pages and "/u/shoes/shoes" not in pages
    assert "/b?sort=price" not in pages and "/search?q=test" not in pages


def test_per_depth_subdomain_and_path_limits(base_url: str) -> None:
    pages = _pages_of(base_url, max_urls_per_depth=5)
    assert sum(1 for p in pages.values() if p["depth"] == 1 and p["parsed"]) <= 5
    pages = _pages_of(base_url, path_limits=[("/l-", 2)])
    assert sum(1 for path, p in pages.items() if path.startswith("/l-") and p["parsed"]) == 2
    pages = _pages_of(base_url, max_urls_per_subdomain=10)
    assert sum(1 for p in pages.values() if not p["external"] and p["parsed"]) <= 10


def test_max_page_size(base_url: str) -> None:
    pages = _pages_of(base_url, max_page_size_kb=100)
    assert pages["/v-big"]["status_code"] == 200 and not pages["/v-big"]["parsed"]
    assert pages["/a"]["parsed"]


def test_5xx_retries(base_url: str) -> None:
    polygon.FLAKY_SEEN.clear()
    assert _pages_of(base_url, "/flaky", retries_5xx=0)["/flaky"]["status_code"] == 503
    polygon.FLAKY_SEEN.clear()
    assert _pages_of(base_url, "/flaky", retries_5xx=2)["/flaky"]["status_code"] == 200


def test_cookies(base_url: str) -> None:
    polygon.SEEN_HEADERS.clear()
    _pages_of(base_url, "/cookie-set")
    assert any("polygon=1" in h.get("cookie", "") for h in polygon.SEEN_HEADERS)
    polygon.SEEN_HEADERS.clear()
    _pages_of(base_url, "/cookie-set", cookies="none")
    assert not any("cookie" in h for h in polygon.SEEN_HEADERS)


def test_basic_auth_only_to_the_site(base_url: str, monkeypatch) -> None:
    monkeypatch.setattr(
        crawl_service.credentials, "get_secret", lambda provider: "pa55" if provider == "site" else None
    )
    assert _pages_of(base_url, "/members/")["/members/"]["status_code"] == 401
    polygon.SEEN_HEADERS.clear()
    assert _pages_of(base_url, "/members/", auth="basic", auth_user="stage")["/members/"]["status_code"] == 200
    monkeypatch.setattr(crawl_service.credentials, "get_secret", lambda provider: None)
    with pytest.raises(AuthRequired):
        _pages_of(base_url, "/members/", auth="basic", auth_user="stage")


def test_other_sites_never_get_the_password(base_url: str, monkeypatch) -> None:
    monkeypatch.setattr(crawl_service.credentials, "get_secret", lambda provider: "pa55")
    polygon.SEEN_HEADERS.clear()
    _pages_of(base_url, "/l-external", auth="basic", auth_user="stage")
    local = {h.get("host", "") for h in polygon.SEEN_HEADERS if h.get("authorization")}
    assert local and all(host.startswith("127.0.0.1") for host in local)  # localhost:port is "another site"


def test_custom_robots_and_the_matched_rule(base_url: str) -> None:
    pages = _pages_of(base_url)
    assert (pages["/private/secret"]["blocked"], pages["/private/secret"]["blocked_rule"]) == (
        "robots_txt",
        "Disallow: /private/",
    )
    pages = _pages_of(base_url, robots_custom="User-agent: *\nDisallow: /a\n")
    assert pages["/a"]["blocked_rule"] == "Disallow: /a" and pages["/private/secret"]["blocked"] is None
    pages = _pages_of(base_url, robots_show_internal_blocked=False)
    assert "/private/secret" not in pages and "/private/hidden.png" not in pages


def test_cdns_are_the_site(base_url: str) -> None:
    pages = _pages_of(base_url, cdns=["localhost"])
    local = f"http://localhost:{base_url.rsplit(':', 1)[1]}"
    with storage.database() as engine, engine.connect() as conn:
        rows = conn.execute(sa.select(storage.pages.c.url, storage.pages.c.external).where(
            storage.pages.c.url.like(f"{local}/%"))).all()  # fmt: skip
    assert rows and not any(external for _, external in rows)
    assert pages  # the crawl itself ran


def test_fragments_and_invalid_links(base_url: str) -> None:
    assert "/a#reviews" in _pages_of(base_url, keep_fragments=True)
    assert "/a#reviews" not in _pages_of(base_url)
    with storage.database() as engine:
        crawl_site(engine, f"{base_url}/l-invalid", "polygon", Settings(crawl=CrawlSettings(crawl_invalid_links=True)))
        with engine.connect() as conn:
            found = conn.execute(
                sa.select(storage.pages.c.status_code).where(storage.pages.c.url == "https:///no-host")
            ).all()
    assert found == [(0,)]  # tried, and of course no answer


def test_list_mode_can_follow_canonicals(base_url: str) -> None:
    with storage.database() as engine:
        plain = crawl_service.register_list_crawl(engine, [f"{base_url}/c-canonicalised"], "p", Settings())
        crawl_service.run_crawl(engine, plain)
        follow = crawl_service.register_list_crawl(
            engine, [f"{base_url}/c-canonicalised"], "p", Settings(crawl=CrawlSettings(list_follow_canonicals=True))
        )
        crawl_service.run_crawl(engine, follow)
        with engine.connect() as conn:

            def urls(crawl_id: int) -> set[str]:
                rows = conn.execute(sa.select(storage.pages.c.url).where(storage.pages.c.crawl_id == crawl_id))
                return {u.removeprefix(base_url) for (u,) in rows}

            assert urls(plain) == {"/c-canonicalised"} and urls(follow) == {"/c-canonicalised", "/a"}


def test_ca_bundle_needs_curl(base_url: str, tmp_path) -> None:
    with pytest.raises(Exception, match=r"needs crawl\.http_client = curl"):
        _pages_of(base_url, "/a", ca_bundle=str(tmp_path / "ca.pem"))
    with pytest.raises(Exception, match="no file"):
        _pages_of(base_url, "/a", ca_bundle=str(tmp_path / "missing.pem"), http_client="curl")


@pytest.mark.skipif(importlib.util.find_spec("curl_cffi") is None, reason="extra rb-spider[curl]")
def test_ca_bundle_trusts_a_private_root(tmp_path) -> None:
    with polygon.serve(https=True) as https_url:
        ca = tmp_path / "root.pem"
        ca.write_bytes(polygon.HTTPS_CA)
        pages = _crawl(https_url, "/plain", http_client="curl", ca_bundle=str(ca), max_urls=1)
    assert pages["/plain"]["status_code"] == 200


def test_uncrawlable_links_are_kept_on_request(base_url: str) -> None:
    settings = Settings(collect=CollectSettings(uncrawlable_links=True))
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/l-uncrawlable", "polygon", settings).crawl_id
        with engine.connect() as conn:
            rows = conn.execute(sa.select(storage.links.c.target, storage.links.c.anchor).where(
                storage.links.c.crawl_id == crawl_id, storage.links.c.kind == "uncrawlable")).all()  # fmt: skip
    assert set(rows) == {("javascript:void(0)", "меню"), ("/a", "псевдоссылка")}


def test_assume_html() -> None:
    body = b"<html><head><title>T</title></head><body><a href='/x'>x</a></body></html>"
    assert parse_page("https://s.example/", 200, {}, body).title == "T"
    assert parse_page("https://s.example/", 200, {}, body, assume_html=False).title is None


def test_self_refresh_and_indexable_only_issues(base_url: str) -> None:
    from rb_spider.core import issues

    with storage.database() as engine:
        crawl_id = crawl_service.register_list_crawl(engine, [f"{base_url}/self-refresh"], "p", Settings())
        crawl_service.run_crawl(engine, crawl_id)
        status = sa.select(storage.pages.c.indexability_status).where(storage.pages.c.crawl_id == crawl_id)
        with engine.connect() as conn:
            assert conn.execute(status).scalar() == "Redirected"
        issues.analyze(engine, crawl_id, ThresholdSettings(self_refresh_non_indexable=False))
        with engine.connect() as conn:
            assert conn.execute(status).scalar() is None

        full = crawl_site(engine, f"{base_url}/", "polygon").crawl_id
        issues.analyze(engine, full, ThresholdSettings(issues_indexable_only=True))
        _, rows = issues.urls_with(engine, full, "content_low_content")
    assert {r["url"].removeprefix(base_url) for r in rows} == {"/thin"}
