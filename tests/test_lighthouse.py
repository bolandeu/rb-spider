"""`spider lighthouse` (#44): typical pages sampled, audits stored, PageSpeed and Mobile rules — with a fake lighthouse
command (no Node.js in tests) and real mobile measures in a browser."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import issues, lighthouse, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.settings import CrawlSettings, Settings

from . import polygon
from .conftest import use_db

FAKE = f"{sys.executable} {Path(__file__).with_name('fake_lighthouse.py')}"
needs_playwright = pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None, reason="the `render` extra is not installed"
)


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture
def crawled(base_url: str, monkeypatch):
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/lh/", "polygon", Settings(crawl=CrawlSettings(max_depth=1))).crawl_id
        use_db(monkeypatch, engine)
        yield engine, crawl_id


def _run(*args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(app, ["--json", "lighthouse", *args, "--set", f"lighthouse.command={json.dumps(FAKE)}"])
    return result.exit_code, json.loads(result.stdout)


def test_templates_and_the_default_sample(crawled, base_url: str) -> None:
    engine, crawl_id = crawled
    assert lighthouse.template("https://s.ru/") == ("", 0)
    assert lighthouse.template("https://s.ru/about") == ("", 1)
    assert lighthouse.template("https://s.ru/catalog/shoes/1") == ("catalog", 3)
    urls = lighthouse.sample(engine, crawl_id, per_template=1, max_pages=20)
    # the biggest template first (/lh/<page>, one of them), then the hub (/lh/, a template of its own)
    assert len(urls) == 2 and urls[0].startswith(f"{base_url}/lh/") and urls[1] == f"{base_url}/lh/"
    assert len(lighthouse.sample(engine, crawl_id, per_template=3, max_pages=20)) == 4
    code, data = _run("--dry-run")
    assert code == 0 and data["urls"] == urls


def test_rules_are_not_checked_until_measured(crawled) -> None:
    engine, crawl_id = crawled
    assert {r.code for r in issues.not_checked(engine, crawl_id)} >= issues.LIGHTHOUSE_CODES


@needs_playwright
@pytest.mark.parametrize("measured", ["all"])
def test_every_rule_finds_its_page(crawled, base_url: str, measured: str) -> None:
    engine, crawl_id = crawled
    code, data = _run("--all")
    assert code == 0 and all(p["ok"] for p in data["pages"]) and data["findings"] > 0
    for code_, paths in polygon.LH_EXPECTED.items():
        _, rows = issues.urls_with(engine, crawl_id, code_)
        assert {r["url"].removeprefix(base_url) for r in rows} == paths, code_
    page = next(p for p in data["pages"] if p["url"].endswith("/lh/unminified-css"))
    assert page["performance"] == 0.5 and page["metrics"]["lcp_ms"] == 2500 and page["failed"] == ["unminified-css"]
    issues.analyze(engine, crawl_id)  # a full analyze keeps what was measured
    assert issues.urls_with(engine, crawl_id, "mobile_content_not_sized")[0] == 1


def test_explicit_urls_errors_and_a_missing_command(crawled, base_url: str) -> None:
    code, data = _run(f"{base_url}/lh/broken-not-in-crawl")
    assert code == 2 and "Not in crawl" in data["error"]["message"]
    code, data = _run(f"{base_url}/lh/", "--all")
    assert code == 2
    code, data = _run(f"{base_url}/lh/", "--strategy", "desktop")
    assert code == 0 and data["strategy"] == "desktop" and [p["url"] for p in data["pages"]] == [f"{base_url}/lh/"]
    result = CliRunner().invoke(app, ["--json", "lighthouse", "--set", "lighthouse.command=no-such-lighthouse-cmd"])
    assert result.exit_code == 1 and json.loads(result.stdout)["error"]["code"] == "LIGHTHOUSE_UNAVAILABLE"


def test_a_failing_run_is_reported_not_fatal(base_url: str, monkeypatch) -> None:
    polygon.OVERRIDES["/lh/broken"] = (200, {}, polygon._html("lh-broken", "/lh/"))
    try:
        with storage.database() as engine:
            crawl_id = crawl_site(
                engine, f"{base_url}/lh/broken", "polygon", Settings(crawl=CrawlSettings(max_depth=0))
            ).crawl_id
            use_db(monkeypatch, engine)
            code, data = _run(f"{base_url}/lh/broken", "--strategy", "desktop", "--crawl", str(crawl_id))
    finally:
        polygon.OVERRIDES.clear()
    assert code == 0 and data["pages"][0]["ok"] is False and "Chrome crashed" in data["pages"][0]["error"]


def test_reports_url_details_and_export(crawled, base_url: str) -> None:
    code, _ = _run(f"{base_url}/lh/unused-css-rules", f"{base_url}/lh/unused-javascript", "--strategy", "desktop")
    assert code == 0
    runner = CliRunner()

    def cli(*args: str) -> dict:
        result = runner.invoke(app, ["--json", *args])
        assert result.exit_code == 0, result.stdout
        return json.loads(result.stdout)

    opportunities = cli("report", "pagespeed")["rows"]
    assert {r["audit"] for r in opportunities} == {"unused-css-rules", "unused-javascript"}
    coverage = cli("report", "pagespeed", "--only", "coverage")["rows"]
    assert {r["kind"] for r in coverage} == {"css", "js"} and all(r["unused_bytes"] == 1000 for r in coverage)
    assert len(cli("report", "pagespeed", "--only", "pages")["rows"]) == 2
    details = cli("url", f"{base_url}/lh/unused-javascript")["lighthouse"]["desktop"]
    assert details["categories"]["performance"] == 0.5 and details["metrics"]["lcp_ms"] == 2500
    assert [a["audit"] for a in details["failed"]] == ["unused-javascript"]
    exported = runner.invoke(app, ["export", "lighthouse"]).stdout
    assert exported.startswith("url,strategy,audit,score") and "unused-javascript" in exported
    doctor = cli("doctor")["checks"]
    assert any(c["name"] == "lighthouse" and c["ok"] for c in doctor)
