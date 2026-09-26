from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import issues, redirects, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.settings import ThresholdSettings

from . import polygon


@pytest.fixture(scope="module")
def polygon_crawl():
    with polygon.serve() as base_url, storage.database() as engine:
        yield base_url, engine, crawl_site(engine, f"{base_url}/", "polygon").crawl_id


def _paths(base_url: str, found: list[redirects.Redirect]) -> set[str]:
    return {r.url.removeprefix(base_url) for r in found}


def test_all_redirects_are_traced_to_their_final_url(polygon_crawl) -> None:
    base_url, engine, crawl_id = polygon_crawl
    by_path = {r.url.removeprefix(base_url): r for r in redirects.report(engine, crawl_id)}
    assert set(by_path) == {
        "/old",
        "/chain1",
        "/chain2",
        "/loop1",
        "/loop2",
        "/to-missing",
        "/meta-refresh",
        "/http-refresh",
    }

    chain = by_path["/chain1"]
    assert [(h.url.removeprefix(base_url), h.status_code, h.type) for h in chain.hops] == [
        ("/chain1", 301, "3xx"),
        ("/chain2", 302, "3xx"),
    ]
    assert (chain.final_url, chain.final_status, chain.loop) == (f"{base_url}/a", 200, False)
    assert by_path["/meta-refresh"].hops[0].type == "meta"
    assert by_path["/loop1"].loop is True
    assert by_path["/loop1"].final_url is None


def test_chains_honour_the_threshold(polygon_crawl) -> None:
    base_url, engine, crawl_id = polygon_crawl
    assert _paths(base_url, redirects.report(engine, crawl_id, "chains")) == {"/chain1", "/loop1", "/loop2"}
    longer = redirects.report(engine, crawl_id, "chains", ThresholdSettings(redirect_chain_hops=3))
    assert _paths(base_url, longer) == {"/loop1", "/loop2"}  # loops always count


def test_errors_are_redirects_landing_on_failures(polygon_crawl) -> None:
    base_url, engine, crawl_id = polygon_crawl
    assert _paths(base_url, redirects.report(engine, crawl_id, "errors")) == {"/to-missing", "/loop1", "/loop2"}


def test_chain_issue_threshold_from_analyze(polygon_crawl) -> None:
    _, engine, crawl_id = polygon_crawl
    issues.analyze(engine, crawl_id, ThresholdSettings(redirect_chain_hops=3))
    assert issues.urls_with(engine, crawl_id, "internal_redirect_chain")[0] == 0
    issues.analyze(engine, crawl_id)
    assert issues.urls_with(engine, crawl_id, "internal_redirect_chain")[0] == 1


def test_cli_redirects_and_analyze_with_threshold() -> None:
    runner = CliRunner()
    with polygon.serve() as base_url:
        assert runner.invoke(app, ["--json", "crawl", f"{base_url}/"]).exit_code == 0
    result = runner.invoke(app, ["--json", "redirects", "--only", "errors", "--limit", "1"])
    data = json.loads(result.stdout)
    assert (result.exit_code, data["total"], len(data["redirects"])) == (0, 3, 1)
    assert data["redirects"][0]["is_error"] is True

    result = runner.invoke(app, ["--json", "analyze", "--set", "thresholds.redirect_chain_hops=3"])
    assert result.exit_code == 0
    summary = json.loads(runner.invoke(app, ["--json", "issues"]).stdout)
    assert "internal_redirect_chain" not in {i["code"] for i in summary["issues"]}
