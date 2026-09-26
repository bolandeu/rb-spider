"""Analysis and export (issue #18): `spider url`, `spider export`, read-only `spider query`."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import storage
from rb_spider.core.crawl import crawl_site

from . import polygon


@pytest.fixture(scope="module")
def _crawl_db(tmp_path_factory):
    """One full polygon crawl in a database of its own, shared by the tests here: (base_url, crawl_id, db path)."""
    path = tmp_path_factory.mktemp("export-db") / "spider.sqlite"
    with polygon.serve() as base_url, storage.database(path) as engine:
        yield base_url, crawl_site(engine, f"{base_url}/", "polygon").crawl_id, path


@pytest.fixture
def crawled(_crawl_db, monkeypatch):
    """(base_url, crawl_id); the commands under test read the shared crawl's database."""
    base_url, crawl_id, path = _crawl_db
    monkeypatch.setenv("SPIDER_DB_PATH", str(path))
    return base_url, crawl_id


def _run(*args: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.stdout


def _json(*args: str) -> tuple[int, dict]:
    code, out = _run("--json", *args)
    return code, json.loads(out)


def _csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def test_url_shows_page_issues_and_resources(crawled) -> None:
    base_url, crawl_id = crawled
    code, data = _json("url", f"{base_url}/i-images")
    assert code == 0 and data["crawl_id"] == crawl_id
    assert data["page"]["status_code"] == 200 and "i-images" in data["page"]["title"]
    assert data["page"]["indexable"] is not None and "indexability_status" in data["page"]
    assert data["outlinks"] >= 1
    images = {r["target"].removeprefix(base_url): r for r in data["resources"] if r["kind"] == "image"}
    assert images["/img/noalt.png"]["alt_attr"] is False
    assert images["/img/big.png"]["bytes"] == 150_000
    assert images["/img/broken.png"]["status_code"] == 404
    assert {r["kind"] for r in data["resources"]} >= {"image", "css", "js"}
    assert "images_missing_alt_attribute" not in {i["code"] for i in data["issues"]}  # reported per image URL

    code, data = _json("url", f"{base_url}/missing")
    assert data["page"]["indexability_status"] == "Client Error"
    assert data["inlinks"] >= 1
    assert "internal_client_error" in {i["code"] for i in data["issues"]}


def test_url_not_in_crawl(crawled) -> None:
    code, data = _json("url", "https://nowhere.example/")
    assert code == 2 and data["error"]["code"] == "INVALID_ARGUMENTS"


def test_url_human_output(crawled) -> None:
    base_url, _ = crawled
    code, out = _run("url", f"{base_url}/i-images")
    assert code == 0 and "Ресурсы" in out and "app.js" in out


def test_export_pages_csv_to_stdout_is_data_only(crawled) -> None:
    base_url, _ = crawled
    code, out = _run("--json", "export")  # --json does not wrap the stream
    assert code == 0
    rows = _csv(out)
    assert {base_url + p for p in polygon.REACHABLE} <= {r["url"] for r in rows}
    assert {"url", "status_code", "indexable", "indexability_status", "title", "word_count"} <= set(rows[0])


def test_export_filters(crawled) -> None:
    base_url, _ = crawled
    _, out = _run("export", "pages", "--issue", "internal_client_error")
    assert {r["url"].removeprefix(base_url) for r in _csv(out)} == polygon.EXPECTED_ISSUES["internal_client_error"]

    _, out = _run("export", "links", "--status", "404")
    rows = _csv(out)
    assert rows and {r["target_status"] for r in rows} == {"404"}
    assert f"{base_url}/missing" in {r["target"] for r in rows}

    _, out = _run("export", "links", "--external", "--format", "json")
    assert json.loads(out) and all(not link["internal"] for link in json.loads(out))

    _, out = _run("export", "issues", "--issue", "internal_redirect_chain", "--format", "json")
    (finding,) = json.loads(out)
    assert finding["name"] == "Internal Redirect Chain" and finding["priority"] and finding["url"].endswith("/chain1")


def test_export_all_issues_to_file(crawled, tmp_path: Path) -> None:
    _, crawl_id = crawled
    target = tmp_path / "issues.csv"
    code, data = _json("export", "issues", "-o", str(target))
    assert code == 0 and data["crawl_id"] == crawl_id and data["dataset"] == "issues"
    rows = _csv(target.read_text(encoding="utf-8"))
    assert data["rows"] == len(rows) and set(polygon.EXPECTED_ISSUES) <= {r["code"] for r in rows}


@pytest.mark.parametrize(
    "args", [["links", "--issue", "internal_client_error"], ["pages", "--issue", "nope"], ["links", "--status", "4x"]]
)
def test_export_rejects_bad_filters(crawled, args: list[str]) -> None:
    code, data = _json("export", *args)
    assert code == 2 and data["error"]["code"] == "INVALID_ARGUMENTS"


def test_query_reads(crawled) -> None:
    _, crawl_id = crawled
    sql = f"SELECT status_code, count(*) AS n FROM pages WHERE crawl_id = {crawl_id} GROUP BY 1 ORDER BY 1"  # noqa: S608 — the test builds its own query
    code, data = _json("query", sql)
    assert code == 0 and data["columns"] == ["status_code", "n"]
    assert any(row[0] == 404 for row in data["rows"]) and not data["truncated"]

    code, data = _json("query", "SELECT url FROM pages", "--limit", "2")
    assert len(data["rows"]) == 2 and data["truncated"]

    code, out = _run("query", "SELECT url FROM pages ORDER BY url", "--format", "csv")
    assert code == 0 and len(_csv(out)) > 2

    code, out = _run("query", "WITH x AS (SELECT casefold('ЁЖ') AS v) SELECT v FROM x")
    assert code == 0 and "ёж" in out


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM pages",
        "UPDATE pages SET title = 'x'",
        "DROP TABLE pages",
        "ATTACH DATABASE 'x.sqlite' AS x",
        "PRAGMA journal_mode = DELETE",
        "SELECT * FROM nope",
        "not sql",
    ],
)
def test_query_refuses_anything_but_reading(crawled, sql: str) -> None:
    code, data = _json("query", sql)
    assert code == 2 and data["error"]["code"] == "INVALID_ARGUMENTS"
    _, data = _json("query", "SELECT count(*) FROM pages")
    assert data["rows"][0][0] > 0  # nothing was changed


def test_url_response_details_and_request_headers(tmp_path, monkeypatch) -> None:
    from rb_spider.core.crawl import crawl_site
    from rb_spider.core.settings import CrawlSettings, Settings

    monkeypatch.setenv("SPIDER_DB_PATH", str(tmp_path / "spider.sqlite"))
    with polygon.serve() as base_url, storage.database() as engine:
        settings = Settings(crawl=CrawlSettings(max_urls=1, user_agent="googlebot", headers={"Accept-Language": "ru"}))
        crawl_site(engine, f"{base_url}/dated", "polygon", settings)
        code, data = _json("url", f"{base_url}/dated")
    page = data["page"]
    assert code == 0 and page["response_ms"] is not None and page["response_ms"] >= 0
    assert page["last_modified"] == "Wed, 01 Jan 2025 10:00:00 GMT"
    assert page["headers"]["last-modified"] == page["last_modified"] and "content-type" in page["headers"]
    assert data["request_headers"]["Accept-Language"] == "ru" and "Googlebot" in data["request_headers"]["User-Agent"]
