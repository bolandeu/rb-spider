"""Pagination (#28): extraction, the report, overview counts and the paginated-duplicates setting."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import issues, pagination, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.extract import parse_page
from rb_spider.core.settings import CollectSettings, FollowStore, Settings, ThresholdSettings

from . import polygon


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture(scope="module")
def crawled(base_url: str):
    with storage.database() as engine:
        yield engine, crawl_site(engine, f"{base_url}/", "polygon").crawl_id


def test_parse_page_reads_link_elements_and_header() -> None:
    headers = {"Content-Type": "text/html", "Link": '<https://s.example/p1>; rel="previous"'}
    body = b'<html><head><link rel="next" href="/p3"><link rel="stylesheet" href="/s.css"></head></html>'
    page = parse_page("https://s.example/p2", 200, headers, body)
    assert page.pagination == [("prev", "https://s.example/p1"), ("next", "https://s.example/p3")]
    assert page.onpage["pagination"] == "paginated"
    first = parse_page("https://s.example/p1", 200, {}, b'<head><link rel="next" href="/p2"></head>')
    assert first.onpage["pagination"] == "first"
    assert parse_page("https://s.example/", 200, {}, b"<p>x</p>").onpage["pagination"] is None


def test_report_filters(base_url: str, crawled) -> None:
    engine, crawl_id = crawled
    total, rows = pagination.report(engine, crawl_id, "all")
    assert total == len(rows) and {"next", "prev"} == {r["rel"] for r in rows}
    _, non_200 = pagination.report(engine, crawl_id, "non_200")
    assert [(r["source"], r["target_status"]) for r in non_200] == [(f"{base_url}/pg-bad", 404)]
    _, unlinked = pagination.report(engine, crawl_id, "unlinked")
    assert {r["target"] for r in unlinked} == {f"{base_url}/pg-un/2"}


def test_overview_counts(crawled) -> None:
    engine, crawl_id = crawled
    with engine.connect() as conn:
        counts = pagination.counts(conn, crawl_id)
    paginated = sum('rel="prev"' in html for html in polygon.PAGINATION_TRAPS.values())
    assert counts == {"contains": len(polygon.PAGINATION_TRAPS), "first_page": len(polygon.PAGINATION_TRAPS) - paginated,
                      "paginated": paginated}  # fmt: skip


def test_paginated_pages_count_as_duplicates_when_asked(base_url: str, crawled) -> None:
    engine, crawl_id = crawled
    try:
        issues.analyze(engine, crawl_id, ThresholdSettings(ignore_paginated_duplicates=False))
        _, rows = issues.urls_with(engine, crawl_id, "page_title_duplicate")
        assert {f"{base_url}/pg-dup/1", f"{base_url}/pg-dup/2"} <= {r["url"] for r in rows}
    finally:
        issues.analyze(engine, crawl_id)


def test_cli_pagination(base_url: str) -> None:
    assert CliRunner().invoke(app, ["--json", "crawl", f"{base_url}/"]).exit_code == 0
    result = CliRunner().invoke(app, ["--json", "pagination", "--only", "non_200"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["total"] == 1 and data["links"][0]["target"] == f"{base_url}/missing"


def test_collect_pagination_off(base_url: str) -> None:
    settings = Settings(collect=CollectSettings(pagination=FollowStore(follow=False, store=False)))
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/", "polygon", settings).crawl_id
        assert pagination.report(engine, crawl_id)[0] == 0
        unchecked = {r.code for r in issues.not_checked(engine, crawl_id)}
    assert "pagination_loop" in unchecked and "pagination_non_indexable" not in unchecked
