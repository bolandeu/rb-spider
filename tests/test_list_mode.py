"""List mode (issue #16): only the listed URLs and their redirect steps, and the result is an ordinary crawl."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import issues, storage
from rb_spider.core.crawl import read_url_list, register_list_crawl, run_crawl
from rb_spider.core.errors import InvalidArguments

from . import polygon


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture
def engine():
    with storage.database() as engine:
        yield engine


def _local(base_url: str) -> str:
    return "http://localhost:" + base_url.rsplit(":", 1)[1]


def _pages(engine, crawl_id: int) -> dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(sa.select(storage.pages).where(storage.pages.c.crawl_id == crawl_id)).mappings()
        return {row["url"]: dict(row) for row in rows}


def test_list_crawl_fetches_the_list_and_follows_only_redirects(base_url: str, engine) -> None:
    listed = [
        f"{base_url}/chain1",
        f"{base_url}/meta-refresh",
        f"{base_url}/private/secret",
        f"{_local(base_url)}/missing",
    ]
    crawl_id = register_list_crawl(engine, listed, "polygon")
    result = run_crawl(engine, crawl_id)

    pages = _pages(engine, crawl_id)
    # redirect steps are followed to the end (3xx and refresh); links on the pages (/a -> /b...) and resources are not
    steps = {f"{base_url}/chain2", f"{base_url}/a", f"{base_url}/c"}
    assert set(pages) == set(listed) | steps
    assert result.status == "finished"
    assert {url: page["depth"] for url, page in pages.items() if url in listed} == dict.fromkeys(listed, 0)
    assert pages[f"{base_url}/private/secret"]["blocked"] == "robots_txt"  # robots.txt applies to the list too
    assert not any(page["external"] for page in pages.values())  # every listed host is "the site"


def test_list_crawl_is_an_ordinary_crawl_for_analysis(base_url: str, engine) -> None:
    crawl_id = register_list_crawl(engine, [f"{base_url}/chain1", f"{base_url}/to-missing"], "polygon")
    run_crawl(engine, crawl_id)

    _, rows = issues.urls_with(engine, crawl_id, "internal_redirect_chain")
    assert [row["url"] for row in rows] == [f"{base_url}/chain1"]
    assert issues.urls_with(engine, crawl_id, "internal_client_error")[1][0]["url"] == f"{base_url}/missing"


def test_read_url_list_skips_comments_blanks_and_duplicates() -> None:
    text = "﻿# migration\nhttps://s.ex/a\n\nhttps://s.ex/a#top\n  https://s.ex/b  \n"
    assert read_url_list(text) == ["https://s.ex/a", "https://s.ex/b"]


@pytest.mark.parametrize("text", ["", "# nothing\n", "https://s.ex/a\n/relative\nftp://s.ex/f\n"])
def test_read_url_list_rejects_empty_and_bad_lists(text: str) -> None:
    with pytest.raises(InvalidArguments):
        read_url_list(text)


def test_cli_crawl_list_file_and_stdin(base_url: str, tmp_path: Path) -> None:
    urls = tmp_path / "urls.txt"
    urls.write_text(f"{base_url}/old\n{base_url}/missing\n")
    result = CliRunner().invoke(app, ["--json", "crawl", "--list", str(urls)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["pages"] == 3  # /old, /a (its redirect target), /missing

    result = CliRunner().invoke(app, ["--json", "crawl", "--list", "-"], input=f"{base_url}/c\n")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["pages"] == 1


@pytest.mark.parametrize(
    "args", [["crawl"], ["crawl", "https://s.ex/", "--list", "x.txt"], ["crawl", "--list", "nope.txt"]]
)
def test_cli_crawl_needs_exactly_one_source(args: list[str]) -> None:
    result = CliRunner().invoke(app, ["--json", *args])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_ARGUMENTS"


def test_list_mode_profile_with_a_single_url(base_url: str, engine) -> None:
    from rb_spider.core.crawl import crawl_site
    from rb_spider.core.settings import CrawlSettings, Settings

    result = crawl_site(engine, f"{base_url}/old", "polygon", Settings(crawl=CrawlSettings(mode="list")))
    pages = _pages(engine, result.crawl_id)
    assert set(pages) == {f"{base_url}/old", f"{base_url}/a"}  # the URL and its redirect, no links followed
    assert not any(page["external"] for page in pages.values())
