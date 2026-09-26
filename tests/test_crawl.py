from __future__ import annotations

import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import issues, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.extract import parse_page

from . import polygon


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture
def engine():
    with storage.database() as engine:
        yield engine


def _pages(engine, crawl_id: int) -> dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(sa.select(storage.pages).where(storage.pages.c.crawl_id == crawl_id)).mappings()
        return {row["url"]: dict(row) for row in rows}


def _invoke_json(*args: str, cwd: Path | None = None) -> tuple[int, dict]:
    result = CliRunner().invoke(app, [*(["--project", str(cwd)] if cwd else []), "--json", *args])
    return result.exit_code, json.loads(result.stdout)


# --- crawl -------------------------------------------------------------------------


def test_crawl_reaches_every_polygon_page(base_url: str, engine) -> None:
    result = crawl_site(engine, f"{base_url}/", "polygon")

    pages = _pages(engine, result.crawl_id)
    assert result.status == "finished"
    assert set(pages) == {base_url + path for path in polygon.REACHABLE}
    assert result.pages == len(polygon.REACHABLE)


def test_crawl_records_status_redirects_titles_and_depth(base_url: str, engine) -> None:
    pages = _pages(engine, crawl_site(engine, f"{base_url}/", "polygon").crawl_id)

    assert pages[f"{base_url}/old"]["status_code"] == 301
    assert pages[f"{base_url}/old"]["redirect_url"] == f"{base_url}/a"  # the hop is stored, not followed silently
    assert pages[f"{base_url}/missing"]["status_code"] == 404
    assert pages[f"{base_url}/a"]["title"] == "Страница A"
    assert pages[f"{base_url}/"]["depth"] == 0
    assert pages[f"{base_url}/c"]["depth"] == 2


def test_crawl_stops_at_max_urls(base_url: str, engine) -> None:
    result = crawl_site(engine, f"{base_url}/", "polygon", max_urls=3)
    assert result.pages == 3


# --- issues ------------------------------------------------------------------------


def test_every_rule_has_a_polygon_trap() -> None:
    assert set(polygon.EXPECTED_ISSUES) == set(issues.BY_CODE)


@pytest.fixture(scope="module")
def polygon_crawl(base_url: str):
    """One full crawl of the polygon shared by the issue tests (crawling is the slow part)."""
    with storage.database() as engine:
        yield engine, crawl_site(engine, f"{base_url}/", "polygon").crawl_id


@pytest.mark.parametrize("code", sorted(polygon.EXPECTED_ISSUES))
def test_rule_finds_exactly_its_trap(code: str, base_url: str, polygon_crawl) -> None:
    engine, crawl_id = polygon_crawl
    _, rows = issues.urls_with(engine, crawl_id, code)
    assert {row["url"].removeprefix(base_url) for row in rows} == polygon.EXPECTED_ISSUES[code]


def test_redirect_details_show_the_path(base_url: str, polygon_crawl) -> None:
    engine, crawl_id = polygon_crawl
    [chain] = issues.urls_with(engine, crawl_id, "internal_redirect_chain")[1]
    assert chain["detail"] == f"2 hops: {base_url}/chain1 → {base_url}/chain2 → {base_url}/a"


def test_summary_puts_high_priority_first(polygon_crawl) -> None:
    engine, crawl_id = polygon_crawl
    priorities = [s.priority for s in issues.summary(engine, crawl_id)]
    assert priorities == sorted(priorities, key=["high", "medium", "low"].index)


def test_analyze_replaces_previous_findings(polygon_crawl) -> None:
    engine, crawl_id = polygon_crawl
    first = issues.analyze(engine, crawl_id)
    assert issues.analyze(engine, crawl_id) == first  # recomputed, not appended


# --- CLI ---------------------------------------------------------------------------


def test_cli_crawl_then_crawls_list(base_url: str) -> None:
    code, crawl = _invoke_json("crawl", f"{base_url}/")
    assert code == 0
    assert crawl["ok"] is True
    assert crawl["project"] == base_url.removeprefix("http://")  # outside a project: the site's host
    assert crawl["pages"] == len(polygon.REACHABLE)

    code, listing = _invoke_json("crawls", "list")
    assert code == 0
    [row] = listing["crawls"]
    assert row["id"] == crawl["crawl_id"]
    assert row["status"] == "finished"
    assert row["started_at"].endswith("+00:00")


def test_cli_crawl_inside_project_uses_project_name(base_url: str, tmp_path: Path) -> None:
    assert CliRunner().invoke(app, ["--project", str(tmp_path), "init", "--name", "shop"]).exit_code == 0
    code, crawl = _invoke_json("crawl", f"{base_url}/", "--max-urls", "1", cwd=tmp_path)
    assert code == 0
    assert crawl["project"] == "shop"


def test_cli_crawl_rejects_relative_url() -> None:
    code, payload = _invoke_json("crawl", "example.com")
    assert code == 2
    assert payload["error"]["code"] == "INVALID_ARGUMENTS"


def test_crawls_list_empty() -> None:
    code, listing = _invoke_json("crawls", "list")
    assert code == 0
    assert listing["crawls"] == []


# --- extract -----------------------------------------------------------------------


def test_parse_page_links_are_absolute_http_without_fragments() -> None:
    body = b'<a href="/x#top">x</a><a href="mailto:a@b">m</a><a href="https://other.example/y">y</a>'
    page = parse_page("https://site.example/dir/", 200, {"Content-Type": "text/html"}, body)
    assert page.links == ["https://site.example/x", "https://other.example/y"]


def test_parse_page_skips_non_html_and_bare_redirects() -> None:
    assert parse_page("https://s.example/f.pdf", 200, {"Content-Type": "application/pdf"}, b"%PDF").links == []
    assert parse_page("https://s.example/r", 302, {}, b"").redirect_url is None


def test_cli_issues_urls_analyze(base_url: str) -> None:
    code, crawl = _invoke_json("crawl", f"{base_url}/")
    assert code == 0

    code, summary = _invoke_json("issues")
    assert code == 0
    assert summary["crawl_id"] == crawl["crawl_id"]
    by_code = {i["code"]: i for i in summary["issues"]}
    assert by_code["internal_client_error"]["urls"] == 1
    assert by_code["internal_client_error"]["priority"] == "high"

    code, listing = _invoke_json("urls", "--issue", "internal_redirection_3xx", "--limit", "2")
    assert code == 0
    assert listing["total"] == len(polygon.EXPECTED_ISSUES["internal_redirection_3xx"])
    assert len(listing["urls"]) == 2

    code, analyzed = _invoke_json("analyze", str(crawl["crawl_id"]))
    assert code == 0
    assert analyzed["findings"] == sum(i["urls"] for i in summary["issues"])


def test_cli_urls_unknown_issue_code(base_url: str) -> None:
    _invoke_json("crawl", f"{base_url}/", "--max-urls", "1")
    code, payload = _invoke_json("urls", "--issue", "no_such_check")
    assert code == 2
    assert "internal_client_error" in payload["error"]["message"]  # lists the known codes


@pytest.mark.parametrize("args", [("issues",), ("issues", "999"), ("analyze",)])
def test_cli_analysis_without_crawl(args: tuple[str, ...]) -> None:
    code, payload = _invoke_json(*args)
    assert code == 2
    assert payload["error"]["code"] == "INVALID_ARGUMENTS"
