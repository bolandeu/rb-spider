"""The page storage of `spider fetch` (ADR 0001): a repeat fetch within the term comes from the storage, not the site.

Every test runs the CLI against the polygon and counts the requests it receives (polygon.SEEN_HEADERS, one entry
per request; Proxy.seen for the proxy). SPIDER_CACHE_DIR and the database are the test's own (conftest).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
import zstandard
from selectolax.parser import HTMLParser
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import fetch_store, storage, tables

from . import polygon
from .test_cli import plain

PAGES = ("/a", "/b", "/old")  # /old: a 301 to /a


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture
def proxy(base_url: str, monkeypatch):
    monkeypatch.setenv("SPIDER_PROXY_API_KEY", polygon.Proxy.PASSWORD)
    with polygon.proxy(base_url) as found:
        yield found


@pytest.fixture
def clock(monkeypatch):
    """Move spider's clock: `clock(days=3)` — every later run sees that time (fetched_at, the term, the cleanup)."""
    start = datetime.now(UTC)

    def move(**delta: float) -> None:
        monkeypatch.setattr(fetch_store, "now", lambda: start + timedelta(**delta))

    move()
    return move


def _run(*args: str) -> list[dict]:
    result = CliRunner().invoke(app, ["--json", "fetch", *args])
    assert result.exit_code == 0, result.output
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def _cache_dir() -> Path:
    return Path(os.environ["SPIDER_CACHE_DIR"])


def _files() -> dict[str, Path]:
    """The stored files by name (without the extension): one per stored fetch, named by its cache_key."""
    return {path.name.split(".")[0]: path for path in _cache_dir().rglob("*") if path.is_file() and path.name[0] != "."}


def _rows() -> dict[str, str]:
    """url → cache_key of every row of spider_fetches."""
    with storage.database() as engine, engine.connect() as conn:
        return dict(conn.execute(sa.select(tables.fetches.c.url, tables.fetches.c.cache_key)).all())


def _requests() -> int:
    return len(polygon.SEEN_HEADERS)


def test_second_run_comes_from_the_storage_without_a_request(base_url: str, proxy: polygon.Proxy) -> None:
    urls = [proxy.base() + path for path in PAGES]
    args = [*urls, "--set", f"crawl.proxy_urls=['{proxy.url}']", "--include", "headers,links,resources,text,markdown"]
    first = _run(*args)
    assert [line["from_cache"] for line in first] == [False, False, False]
    assert all(line["cache_key"] and line["content_hash"] for line in first)
    polygon_before, proxy_before = _requests(), len(proxy.seen)

    second = _run(*args)

    assert [line["from_cache"] for line in second] == [True, True, True]
    assert _requests() == polygon_before and len(proxy.seen) == proxy_before  # no page, no proxy check
    for live, stored in zip(first, second, strict=True):
        assert stored["cache_key"] == live["cache_key"] and stored["content_hash"] == live["content_hash"]
        assert stored["fetched_at"] == live["fetched_at"]  # the stored time
        # the same output as the live fetch of the same source
        drop = ("from_cache", "elapsed_ms", "via")
        assert {k: v for k, v in stored.items() if k not in drop} == {k: v for k, v in live.items() if k not in drop}
    assert second[2]["final_url"] == f"{proxy.base()}/a" and second[2]["redirects"][0]["status"] == 301


def test_human_output_marks_a_stored_page(base_url: str) -> None:
    _run(f"{base_url}/a")
    result = CliRunner().invoke(app, ["fetch", f"{base_url}/a"])
    assert result.exit_code == 0 and "из хранилища" in " ".join(plain(result.stdout).split())  # rich wraps long lines


def test_fresh_fetches_again_and_replaces_the_stored_file(base_url: str) -> None:
    [old] = _run(f"{base_url}/a")
    assert set(_files()) == {old["cache_key"]}
    before = _requests()

    [new] = _run(f"{base_url}/a", "--fresh")

    assert _requests() == before + 1 and new["from_cache"] is False
    assert new["cache_key"] != old["cache_key"] and new["content_hash"] == old["content_hash"]
    assert set(_files()) == {new["cache_key"]}  # the old file is deleted
    assert _rows() == {f"{base_url}/a": new["cache_key"]}  # one row per URL and mode
    [again] = _run(f"{base_url}/a")
    assert again["from_cache"] is True and again["cache_key"] == new["cache_key"]


def test_max_age_shorter_than_the_age_is_a_miss(base_url: str, clock) -> None:
    [old] = _run(f"{base_url}/a")
    clock(days=3)
    [kept] = _run(f"{base_url}/a", "--max-age", "5")
    assert kept["from_cache"] is True and kept["cache_key"] == old["cache_key"]
    before = _requests()

    [new] = _run(f"{base_url}/a", "--max-age", "2")

    assert _requests() == before + 1 and new["from_cache"] is False and new["cache_key"] != old["cache_key"]
    assert set(_files()) == {new["cache_key"]}
    assert datetime.fromisoformat(new["fetched_at"]) - datetime.fromisoformat(old["fetched_at"]) >= timedelta(days=3)


def test_render_mode_is_stored_apart(base_url: str) -> None:
    """One row per URL and mode: a stored fetch without --render does not answer a --render fetch."""
    pytest.importorskip("playwright")
    _run(f"{base_url}/js-only")
    before = _requests()
    [rendered] = _run(f"{base_url}/js-only", "--render")
    assert rendered["from_cache"] is False and _requests() > before
    [again] = _run(f"{base_url}/js-only", "--render")
    assert again["from_cache"] is True and again["seo"]["title"] == "Заголовок из JS"


def test_every_line_has_the_keys_and_what_is_not_stored(base_url: str, monkeypatch) -> None:
    monkeypatch.setitem(polygon.OVERRIDES, "/busy", (429, {}, "<html><body>Подождите</body></html>"))
    urls = [f"{base_url}{path}" for path in ("/a", "/missing", "/error", "/busy", "/style.css")]
    dead = "http://127.0.0.1:1/x"
    lines = _run(*urls, dead)
    keys = {"url_key", "domain_key", "content_hash", "cache_key", "fetched_at", "from_cache"}
    assert all(keys <= set(line) for line in lines)
    a, missing, error, busy, css, gone = lines
    host = base_url.removeprefix("http://")  # 127.0.0.1:<port>: rb-keys drops the scheme, keeps a non-default port
    assert (a["url_key"], a["domain_key"]) == (f"{host}/a", host)
    assert datetime.fromisoformat(a["fetched_at"]).utcoffset() == timedelta(0)
    assert missing["status"] == 404 and missing["cache_key"]  # an answer below 500 is stored
    for line in (error, busy, css, gone):  # 5xx, 429, not HTML, no answer: not stored
        assert line["content_hash"] is None and line["cache_key"] is None and line["from_cache"] is False
    assert gone["status"] is None and gone["error"] and gone["url_key"] == "127.0.0.1:1/x"
    before = _requests()

    again = _run(*urls, dead)

    assert [line["from_cache"] for line in again] == [True, True, False, False, False, False]
    assert _requests() == before + 3  # /error, /busy, /style.css are fetched every time


def test_stored_file_is_zstd_with_the_html_and_the_markdown(base_url: str) -> None:
    [line] = _run(f"{base_url}/a")
    raw = zstandard.ZstdDecompressor().decompress(_files()[line["cache_key"]].read_bytes())
    header, source = raw.split(b"\n", 1)  # one JSON line, then the page source
    data = json.loads(header)
    assert data["markdown"].startswith(f"# {polygon.H1.format('a')}")
    assert data["final_url"] == f"{base_url}/a" and data["status"] == 200 and data["rendered"] is None
    assert data["headers"]["content-type"] == "text/html; charset=utf-8"
    title = HTMLParser(source).css_first("title")
    assert title is not None and title.text() == polygon.TITLE.format("a")
    assert hashlib.sha256(source).hexdigest() == line["content_hash"]


def test_a_row_without_its_file_is_a_miss(base_url: str) -> None:
    [old] = _run(f"{base_url}/a")
    _files()[old["cache_key"]].unlink()
    before = _requests()
    [new] = _run(f"{base_url}/a")
    assert new["from_cache"] is False and _requests() == before + 1 and new["cache_key"] in _files()


def test_daily_cleanup_deletes_expired_fetches(base_url: str, clock, monkeypatch) -> None:
    monkeypatch.setenv("SPIDER_CACHE_TTL_DAYS", "1")
    [short] = _run(f"{base_url}/a")
    monkeypatch.setenv("SPIDER_CACHE_TTL_DAYS", "5")
    [long] = _run(f"{base_url}/b")
    clock(days=2)

    _run(f"{base_url}/c")

    assert set(_rows()) == {f"{base_url}/b", f"{base_url}/c"}
    assert short["cache_key"] not in _files() and long["cache_key"] in _files()


def test_cleanup_runs_at_most_once_a_day(base_url: str, clock, monkeypatch) -> None:
    monkeypatch.setenv("SPIDER_CACHE_TTL_DAYS", "0")  # every fetch expires at once
    _run(f"{base_url}/a")  # the day's cleanup, then /a is stored
    clock(hours=23)
    _run(f"{base_url}/b")  # within the day: no cleanup, the expired /a stays
    assert set(_rows()) == {f"{base_url}/a", f"{base_url}/b"}
    clock(hours=25)

    _run(f"{base_url}/c")

    assert set(_rows()) == {f"{base_url}/c"}


def test_cleanup_deletes_the_oldest_over_the_limit(base_url: str, clock, monkeypatch) -> None:
    lines = {}
    for hour, path in enumerate(("/a", "/b", "/c")):
        clock(hours=hour)
        [lines[path]] = _run(f"{base_url}{path}")
    files = _files()
    keep = sum(files[lines[path]["cache_key"]].stat().st_size for path in ("/b", "/c"))
    monkeypatch.setenv("SPIDER_CACHE_MAX_GB", str((keep + 0.5) / 1e9))  # GB = 10**9 bytes
    clock(days=2)

    [hit] = _run(f"{base_url}/c")

    assert hit["from_cache"] is True
    assert set(_rows()) == {f"{base_url}/b", f"{base_url}/c"}
    assert set(_files()) == {lines["/b"]["cache_key"], lines["/c"]["cache_key"]}


def test_library_does_not_store_unless_asked(base_url: str) -> None:
    from rb_spider.fetch import fetch

    page = fetch(f"{base_url}/a")
    assert (
        page.from_cache is False and page.cache_key is None and page.url_key == f"{base_url.removeprefix('http://')}/a"
    )
    assert _files() == {}
    stored = fetch(f"{base_url}/a", store=True)
    assert stored.cache_key in _files()
    before = _requests()
    again = fetch(f"{base_url}/a", store=True)
    assert again.from_cache is True and _requests() == before


def test_cleanup_deletes_files_without_a_row_older_than_a_day(base_url: str, clock) -> None:
    start = fetch_store.now()
    [stored] = _run(f"{base_url}/a")  # the day's cleanup runs here
    orphans = {}
    for name, age in (("old", timedelta(days=2)), ("young", timedelta(hours=1))):
        # a run that stopped between the file and its row leaves such a file
        path = _cache_dir() / name[:2] / f"{name}.zst"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"orphan")
        moment = (start + timedelta(days=1, hours=1) - age).timestamp()
        os.utime(path, (moment, moment))
        orphans[name] = path
    clock(days=1, hours=1)

    _run(f"{base_url}/b")

    assert not orphans["old"].exists()
    assert orphans["young"].exists()  # it may be a save in progress
    assert stored["cache_key"] in _files()
