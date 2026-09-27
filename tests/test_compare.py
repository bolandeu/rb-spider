"""Comparing crawls and re-spidering (#37): the polygon crawled twice, changed in between."""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import compare, storage
from rb_spider.core import crawl as crawl_service
from rb_spider.core.crawl import crawl_site

from . import polygon
from .conftest import use_db

CHANGES = {
    "/a": (
        200,
        {},
        polygon._html("a", "/c", head=polygon._head("a", title="Новый заголовок страницы a для сравнения")),
    ),
    "/t-missing": (200, {}, polygon._html("t-missing")),  # the title is back: page_title_missing removed
    "/deep3": (200, {}, polygon._html("deep3", "/")),  # /deep4 is no longer linked: gone from the crawl
    "/c": (200, {}, polygon._html("c", "/cmp-new")),
    "/cmp-new": (200, {}, polygon._html("cmp-new", thin=True)),  # a new URL with low content
}


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture(scope="module")
def two_crawls(base_url: str):
    with storage.database() as engine:
        old = crawl_site(engine, f"{base_url}/", "polygon").crawl_id
        polygon.OVERRIDES.update(CHANGES)
        try:
            new = crawl_site(engine, f"{base_url}/", "polygon").crawl_id
        finally:
            polygon.OVERRIDES.clear()
        yield engine, old, new


def _paths(rows: list[dict], base_url: str) -> set[str]:
    return {row["url"].removeprefix(base_url) for row in rows}


def test_summary(two_crawls) -> None:
    engine, old, new = two_crawls
    data = compare.summary(engine, old, new, list(compare.FIELDS))
    assert (data["urls"]["new_urls"], data["urls"]["missing_urls"]) == (1, 1)
    by_code = {row["code"]: row for row in data["issues"]}
    assert by_code["page_title_missing"]["removed"] == 1
    assert by_code["links_high_crawl_depth"]["missing"] == 1
    assert by_code["content_low_content"]["new_urls"] == 1
    assert data["changes"]["title"] >= 2 and data["changes"]["content"] >= 4


def test_details(base_url: str, two_crawls) -> None:
    engine, old, new = two_crawls
    total, rows = compare.details(engine, old, new, issue="page_title_missing", status="removed")
    assert (total, _paths(rows, base_url)) == (1, {"/t-missing"})
    _, rows = compare.details(engine, old, new, issue="content_low_content", status="new")
    assert _paths(rows, base_url) == {"/cmp-new"}
    _, rows = compare.details(engine, old, new, issue="links_high_crawl_depth", status="missing")
    assert _paths(rows, base_url) == {"/deep4"}
    _, rows = compare.details(engine, old, new, field="title")
    a = next(r for r in rows if r["url"].endswith("/a"))
    assert (a["old"], a["new"]) == (polygon.TITLE.format("a"), "Новый заголовок страницы a для сравнения")
    assert _paths(compare.details(engine, old, new, urls="new")[1], base_url) == {"/cmp-new"}
    assert _paths(compare.details(engine, old, new, urls="missing")[1], base_url) == {"/deep4"}


def test_cli_compare(two_crawls, monkeypatch) -> None:
    engine, old, new = two_crawls
    use_db(monkeypatch, engine)
    runner = CliRunner()
    result = runner.invoke(app, ["--json", "compare", str(old), str(new), "--set", 'compare.fields=["title"]'])
    assert result.exit_code == 0
    assert list(json.loads(result.stdout)["changes"]) == ["title"]
    assert "Проблемы" in runner.invoke(app, ["compare", str(old), str(new)]).stdout
    listed = json.loads(runner.invoke(app, ["--json", "compare", str(old), str(new), "--urls", "missing"]).stdout)
    assert listed["total"] == 1
    assert runner.invoke(app, ["--json", "compare", str(old), str(new), "--field", "nope"]).exit_code == 2
    assert (
        runner.invoke(app, ["--json", "compare", str(old), str(new), "--urls", "new", "--field", "title"]).exit_code
        == 2
    )


def test_respider_replaces_the_chosen_pages(base_url: str) -> None:
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/", "polygon").crawl_id
        polygon.OVERRIDES.update(CHANGES)
        try:
            result = crawl_service.respider(engine, crawl_id, [f"{base_url}/a", f"{base_url}/c"])
        finally:
            polygon.OVERRIDES.clear()
        assert result.status == "finished" and result.pages == len(polygon.REACHABLE) + len(polygon.EXTERNAL)
        with engine.connect() as conn:
            title = conn.execute(sa.select(storage.pages.c.title).where(
                storage.pages.c.crawl_id == crawl_id, storage.pages.c.url == f"{base_url}/a")).scalar()  # fmt: skip
            out = {t for (t,) in conn.execute(sa.select(storage.links.c.target).where(
                storage.links.c.crawl_id == crawl_id, storage.links.c.source == f"{base_url}/c"))}  # fmt: skip
            new_page = conn.execute(sa.select(storage.pages.c.url).where(
                storage.pages.c.url == f"{base_url}/cmp-new")).first()  # fmt: skip
        assert title == "Новый заголовок страницы a для сравнения"
        assert f"{base_url}/cmp-new" in out and f"{base_url}/" not in out  # the old link of /c is gone
        assert new_page is None  # linked now, not followed
        with pytest.raises(Exception, match="Not in crawl"):
            crawl_service.respider(engine, crawl_id, [f"{base_url}/never"])


def test_cli_respider(base_url: str) -> None:
    runner = CliRunner()
    crawl = json.loads(runner.invoke(app, ["--json", "crawl", f"{base_url}/", "--max-urls", "5"]).stdout)
    result = runner.invoke(app, ["--json", "crawls", "respider", str(crawl["crawl_id"]), f"{base_url}/"])
    assert result.exit_code == 0 and json.loads(result.stdout)["pages"] == 5
    assert runner.invoke(app, ["--json", "crawls", "respider", str(crawl["crawl_id"])]).exit_code == 2


# --- URL Mapping (#53) -------------------------------------------------------------


def test_url_mapping_matches_the_same_pages_on_another_host(base_url: str, monkeypatch) -> None:
    """The same site crawled as 127.0.0.1 and as localhost: without mapping every URL is new / missing."""
    port = base_url.rsplit(":", 1)[1]
    with storage.database() as engine:
        old = crawl_site(engine, f"{base_url}/", "polygon").crawl_id
        new = crawl_site(engine, f"http://localhost:{port}/", "polygon").crawl_id
        plain = compare.summary(engine, old, new, ["title"])
        assert plain["urls"]["missing_urls"] == plain["urls"]["old"] > 100
        rules = [(r"^http://127\.0\.0\.1:(\d+)", r"http://localhost:\1")]
        mapped = compare.summary(engine, old, new, ["title", "status_code"], rules)
        assert mapped["urls"]["missing_urls"] == 0
        # the polygon's "other site" traps live on localhost: crawled from localhost, one of them is the site's own
        _, fresh = compare.details(engine, old, new, urls="new", mapping=rules)
        assert _paths(fresh, f"http://localhost:{port}") == {"/img/gone.png"}
        assert mapped["changes"] == {"title": 0, "status_code": 0}
        assert all(row["added"] == 0 for row in mapped["issues"])  # matched pages: nothing new about them
        assert compare.details(engine, old, new, urls="missing", mapping=rules)[0] == 0

        use_db(monkeypatch, engine)
        result = CliRunner().invoke(app, ["--json", "compare", str(old), str(new), "--map",
                                          r"^http://127\.0\.0\.1:(\d+)=>http://localhost:\1"])  # fmt: skip
        assert result.exit_code == 0 and json.loads(result.stdout)["urls"]["missing_urls"] == 0
        bad = CliRunner().invoke(app, ["--json", "compare", str(old), str(new), "--map", "no-arrow"])
        assert bad.exit_code == 2
