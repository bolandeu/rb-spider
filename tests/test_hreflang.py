"""Hreflang (#27): extraction, the report and the overview counts on the polygon; the checks are in test_crawl."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import hreflang, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.extract import parse_page
from rb_spider.core.settings import CollectSettings, FollowStore, Settings

from . import polygon


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture(scope="module")
def crawled(base_url: str):
    with storage.database() as engine:
        yield engine, crawl_site(engine, f"{base_url}/", "polygon").crawl_id


def _invoke(*args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(app, ["--json", *args])
    return result.exit_code, json.loads(result.stdout)


def test_parse_page_reads_html_and_header_annotations() -> None:
    headers = {"Content-Type": "text/html", "Link": '<https://s.example/de>; rel="alternate"; hreflang="de"'}
    body = (b'<html><head><link rel="alternate" hreflang="en" href="/en"><link rel="alternate" href="/x">'
            b'</head><body><link rel="alternate" hreflang="fr" href="/fr"></body></html>')  # fmt: skip
    page = parse_page("https://s.example/", 200, headers, body)
    assert page.hreflang == [
        ("de", "https://s.example/de"),
        ("en", "https://s.example/en"),
        ("fr", "https://s.example/fr"),
    ]
    assert page.onpage["hreflang_outside_head"] == 1


@pytest.mark.parametrize(("code", "valid"), [("en", True), ("en-GB", True), ("en-UK", False), ("x-default", True),
                                             ("zh-Hant-TW", True), ("english", False), ("iw", False)])  # fmt: skip
def test_valid_code(code: str, valid: bool) -> None:
    assert hreflang.valid_code(code) is valid


def test_report_filters(base_url: str, crawled) -> None:
    engine, crawl_id = crawled
    total, rows = hreflang.report(engine, crawl_id, "all")
    header = [r for r in rows if r["source"] == f"{base_url}/hl/header"]
    assert {r["hreflang"] for r in header} == {"en", "x-default"}  # the Link header counts
    assert total == len(rows)

    _, missing_return = hreflang.report(engine, crawl_id, "missing_return")
    assert {(r["source"], r["target"]) for r in missing_return} >= {(f"{base_url}/hl/noreturn", f"{base_url}/hl/ru")}
    assert all(r["return_link"] is False for r in missing_return)

    _, non_200 = hreflang.report(engine, crawl_id, "non_200")
    assert [(r["target"], r["target_status"]) for r in non_200] == [(f"{base_url}/missing", 404)]

    _, missing = hreflang.report(engine, crawl_id, "missing", limit=5)
    assert len(missing) == 5 and all(r["target"] is None for r in missing)


def test_overview_counts_pages_with_and_without_hreflang(crawled) -> None:
    engine, crawl_id = crawled
    with engine.connect() as conn:
        counts = hreflang.counts(conn, crawl_id)
    assert counts["contains"] == len(polygon.HREFLANG_TRAPS) + 1  # and /hl/header


def test_cli_hreflang(base_url: str) -> None:
    assert _invoke("crawl", f"{base_url}/")[0] == 0
    code, data = _invoke("hreflang", "--only", "unlinked")
    assert code == 0
    assert {r["target"] for r in data["annotations"]} == {f"{base_url}/hl/unl-fr"}
    assert data["total"] == len(data["annotations"])


def test_collect_hreflang_off_leaves_no_rows_and_rules_unchecked(base_url: str) -> None:
    from rb_spider.core import issues

    settings = Settings(collect=CollectSettings(hreflang=FollowStore(follow=False, store=False)))
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/", "polygon", settings).crawl_id
        assert hreflang.report(engine, crawl_id, "all")[0] == 0
        unchecked = {r.code for r in issues.not_checked(engine, crawl_id)}
    assert "hreflang_missing_return" in unchecked and "hreflang_outside_head" not in unchecked
