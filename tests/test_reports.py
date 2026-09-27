"""Exports and reports v2 (#38): XLSX, presets, bulk datasets, link exports by issue and the `spider report` group."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import reports, storage
from rb_spider.core.crawl import crawl_site, read_url_list
from rb_spider.core.extract import path_type
from rb_spider.core.settings import CrawlSettings, Settings

from . import polygon
from .conftest import db_env, use_db


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture(scope="module")
def crawled(base_url: str, tmp_path_factory):
    """One polygon crawl with stored HTML, shared through SPIDER_DB_PATH by every CLI test of the module."""
    db = tmp_path_factory.mktemp("reports") / "spider.sqlite"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SPIDER_DB_PATH", str(db))
        with storage.database() as engine:
            crawl_site(engine, f"{base_url}/", "polygon", Settings(crawl=CrawlSettings(store_html=True)))
            env = db_env() | db_env(engine)
    yield env


def _run(db: dict[str, str], *args: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, list(args), env=db)
    return result.exit_code, result.stdout


def _json(db: dict[str, str], *args: str) -> dict:
    code, out = _run(db, "--json", *args)
    assert code == 0, out
    return json.loads(out)


csv.field_size_limit(10**8)  # the source of the 2 MB page


def _csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def test_xlsx_export_and_presets(crawled: dict[str, str], tmp_path: Path) -> None:
    data = _json(crawled, "export", "issues", "--format", "xlsx", "-o", str(tmp_path / "issues.xlsx"))
    sheet = load_workbook(tmp_path / "issues.xlsx", read_only=True).worksheets[0]
    assert data["rows"] == sum(1 for _ in sheet.iter_rows()) - 1 > 10
    data = _json(crawled, "export", "--preset", "audit", "-o", str(tmp_path / "audit.xlsx"))
    book = load_workbook(tmp_path / "audit.xlsx", read_only=True)
    assert book.sheetnames == ["pages", "issues", "links"] and set(data["files"]) == set(book.sheetnames)
    data = _json(crawled, "export", "--preset", "links", "-o", str(tmp_path / "links"), "--format", "json")
    assert (tmp_path / "links" / "links-links_no_anchor_text.json").is_file() and data["files"]["links"] > 100
    assert _run(crawled, "--json", "export", "--format", "xlsx")[0] == 2  # xlsx needs -o
    assert _run(crawled, "--json", "export", "--preset", "nope", "-o", str(tmp_path / "x"))[0] == 2


@pytest.mark.parametrize(
    ("dataset", "column", "expect"),
    [
        ("headers", "name", "content-security-policy"),
        ("source", "html", "<html>"),
        ("text", "text", "простой текст"),
        ("queued", "url", None),  # a finished crawl: an empty queue
    ],
)
def test_bulk_datasets(crawled: dict[str, str], dataset: str, column: str, expect: str | None) -> None:
    code, out = _run(crawled, "export", dataset)
    assert code == 0
    rows = _csv(out)
    if expect is None:
        assert rows == []
    else:
        assert any(expect in (row[column] or "") for row in rows)


def test_links_by_issue_and_path_type(crawled: dict[str, str], base_url: str) -> None:
    code, out = _run(crawled, "export", "links", "--issue", "links_no_anchor_text")
    rows = _csv(out)
    assert code == 0 and {r["source"].removeprefix(base_url) for r in rows} == {"/l-no-anchor"}
    code, out = _run(crawled, "export", "links", "--issue", "internal_client_error")
    assert {r["target"].removeprefix(base_url) for r in _csv(out)} >= {"/missing"}
    assert _run(crawled, "--json", "export", "links", "--issue", "page_title_missing")[0] == 2
    code, out = _run(crawled, "export", "links")
    types = {r["path_type"] for r in _csv(out) if r["kind"] == "hyperlink"}
    assert {"root-relative", "absolute"} <= types
    assert [path_type(h) for h in ("https://a/", "//a/", "/a", "a", "?q")] == ["a", "p", "r", "l", "l"]


def test_redirect_and_canonical_chains(crawled: dict[str, str], base_url: str) -> None:
    plain = _json(crawled, "redirects", "--only", "all")
    with_canonicals = _json(crawled, "redirects", "--only", "all", "--canonicals")
    assert with_canonicals["total"] > plain["total"]
    hops = [hop["type"] for r in with_canonicals["redirects"] for hop in r["hops"]]
    assert "canonical" in hops


def test_canonicals_report(crawled: dict[str, str], base_url: str) -> None:
    rows = _json(crawled, "report", "canonicals", "--only", "non_indexable")["rows"]
    assert {r["url"].removeprefix(base_url) for r in rows} == {"/c-nonindexable"}
    everything = _json(crawled, "report", "canonicals", "--only", "all")
    assert everything["total"] >= len(polygon.EXPECTED_ISSUES["canonical_canonicalised"])


def test_structure_times_path(crawled: dict[str, str], base_url: str) -> None:
    structure = _json(crawled, "report", "structure", "--depth", "1")
    folders = {f["folder"]: f for f in structure["folders"]}
    assert folders["/shop/"]["urls"] >= 2 and structure["depths"]["0"] == 1
    times = _json(crawled, "report", "response-times", "--slowest", "3")
    assert sum(times["bands"].values()) == times["urls"] and len(times["slowest"]) == 3
    path = _json(crawled, "report", "crawl-path", f"{base_url}/deep4")["path"]
    assert [step["url"].removeprefix(base_url) for step in path] == ["/", "/deep1", "/deep2", "/deep3", "/deep4"]
    assert path[0]["via"] is None and {step["via"] for step in path[1:]} == {"hyperlink"}
    assert _run(crawled, "--json", "report", "crawl-path", f"{base_url}/nowhere")[0] == 2


def test_forms_and_headers(crawled: dict[str, str], base_url: str) -> None:
    forms = _json(crawled, "report", "forms")["rows"]
    assert {(f["page"].removeprefix(base_url), f["insecure"]) for f in forms} == {("/s-form", 1)}
    headers = {h["name"]: h for h in _json(crawled, "report", "headers")["rows"]}
    assert headers["content-type"]["urls"] > 100
    assert "Заголовки ответа" in _run(crawled, "report", "headers")[1]


def test_cookie_and_keyword_reports(base_url: str, tmp_path: Path) -> None:
    db = db_env()  # this test's own database
    paths = ["/cookie-set", "/mk-1", "/mk-2", "/mk-3", "/a"]
    (tmp_path / "urls.txt").write_text("\n".join(base_url + p for p in paths))
    assert _run(db, "--json", "crawl", "--list", str(tmp_path / "urls.txt"))[0] == 0
    cookies = _json(db, "report", "headers", "--cookies")["rows"]
    assert cookies[0]["name"] == "polygon" and "path" in cookies[0]["attributes"]
    assert _csv(_run(db, "export", "cookies")[1])[0]["name"] == "polygon"
    dup = _json(db, "report", "meta-keywords", "--only", "duplicate")["rows"]
    assert {r["url"].removeprefix(base_url) for r in dup} == {"/mk-1", "/mk-2"}
    multiple = _json(db, "report", "meta-keywords", "--only", "multiple")["rows"]
    assert [r["url"].removeprefix(base_url) for r in multiple] == ["/mk-3"]
    assert _json(db, "report", "meta-keywords", "--only", "missing")["total"] == 2  # /cookie-set, /a


def test_robots_tester(base_url: str, tmp_path: Path) -> None:
    db = db_env()
    rows = _json(db, "robots-test", f"{base_url}/private/x", f"{base_url}/a")["rows"]
    assert [(r["allowed"], r["rule"]) for r in rows] == [(False, "Disallow: /private/"), (True, None)]
    rows = _json(db, "robots-test", f"{base_url}/g-blocked", "--user-agent", "Googlebot")["rows"]
    assert rows[0]["allowed"] is False
    edited = tmp_path / "robots.txt"
    edited.write_text("User-agent: *\nDisallow: /a\n")
    rows = _json(db, "robots-test", f"{base_url}/a", f"{base_url}/private/x", "--robots", str(edited))["rows"]
    assert [r["allowed"] for r in rows] == [False, True]
    assert "запрещён" in _run(db, "robots-test", f"{base_url}/private/x")[1]


def test_excel_url_list(tmp_path: Path) -> None:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(["Address", "Status Code"])
    sheet.append(["https://s.example/a", 200])
    sheet.append(["https://s.example/b", 404])
    book.save(tmp_path / "urls.xlsx")
    from rb_spider.commands.options import read_url_source

    assert read_url_list(read_url_source(str(tmp_path / "urls.xlsx"))) == ["https://s.example/a", "https://s.example/b"]


def test_structure_counts_stay_per_folder(crawled: dict[str, str], monkeypatch) -> None:
    use_db(monkeypatch, env=crawled)
    with storage.database() as engine:
        data = reports.structure(engine, storage.resolve_crawl_id(engine, None), depth=1)
    assert all(f["urls"] == f["indexable"] + f["non_indexable"] for f in data["folders"])
