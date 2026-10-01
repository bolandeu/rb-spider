"""Link Score (v3): internal PageRank 0–100, only on request (`spider link-score`) and only from stored internal links."""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.settings import CollectSettings, FollowStore, Settings

from . import polygon
from .conftest import db_env


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


def _scores(engine, crawl_id: int, base_url: str) -> dict[str, int | None]:
    with engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT url, link_score FROM spider_pages WHERE crawl_id = :c AND NOT coalesce(external,"
                                    " FALSE)"), {"c": crawl_id})  # fmt: skip
        return {url.removeprefix(base_url): score for url, score in rows}


def _run(engine, *args: str):
    result = CliRunner().invoke(app, ["--json", "link-score", *args], env=db_env(engine))
    return result.exit_code, json.loads(result.stdout)


def test_not_computed_until_asked_then_home_page_on_top(base_url: str) -> None:
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/", "polygon").crawl_id
        assert set(_scores(engine, crawl_id, base_url).values()) == {None}  # the crawl and analyze don't compute it
        code, data = _run(engine, str(crawl_id), "--limit", "3")
        assert code == 0 and data["pages"] > 100 and len(data["top"]) == 3
        assert data["top"][0]["url"] == f"{base_url}/" and data["top"][0]["link_score"] == 100
        scores = _scores(engine, crawl_id, base_url)
        assert all(1 <= s <= 100 for s in scores.values() if s is not None)
        assert (scores["/pg/2"] or 0) > (scores["/m/page"] or 0)  # three inlinks against one from a page nobody links
        assert scores["/app.js"] is None  # a resource, not a page


def test_needs_the_internal_links(base_url: str) -> None:
    with storage.database() as engine:
        settings = Settings(collect=CollectSettings(internal_links=FollowStore(follow=True, store=False)))
        crawl_id = crawl_site(engine, f"{base_url}/a", "polygon", settings).crawl_id
        code, data = _run(engine, str(crawl_id))
        assert code == 2 and data["error"]["code"] == "INTERNAL_LINKS_NOT_COLLECTED"
        assert "collect.internal_links.store=true" in data["error"]["action"]
