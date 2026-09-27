"""Link Score (v3): internal PageRank 0–100, computed after the crawl when thresholds.link_score is on."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from rb_spider.core import issues, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.settings import Settings, ThresholdSettings

from . import polygon


@pytest.fixture(scope="module")
def crawled():
    with polygon.serve() as base_url, storage.database() as engine:
        settings = Settings(thresholds=ThresholdSettings(link_score=True))
        yield engine, crawl_site(engine, f"{base_url}/", "polygon", settings).crawl_id, base_url


def _scores(engine, crawl_id: int, base_url: str) -> dict[str, int | None]:
    with engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT url, link_score FROM pages WHERE crawl_id = :c AND NOT coalesce(external,"
                                    " FALSE)"), {"c": crawl_id})  # fmt: skip
        return {url.removeprefix(base_url): score for url, score in rows}


def test_home_page_has_the_top_score_and_every_page_one(crawled) -> None:
    engine, crawl_id, base_url = crawled
    scores = _scores(engine, crawl_id, base_url)
    assert scores["/"] == 100
    assert all(1 <= s <= 100 for s in scores.values() if s is not None)
    assert (scores["/pg/2"] or 0) > (scores["/m/page"] or 0)  # three inlinks against one from a page nobody links
    assert scores["/app.js"] is None  # a resource, not a page


def test_off_by_default_and_cleared_on_reanalysis(crawled) -> None:
    engine, crawl_id, base_url = crawled
    issues.analyze(engine, crawl_id, ThresholdSettings())
    assert set(_scores(engine, crawl_id, base_url).values()) == {None}
    issues.analyze(engine, crawl_id, ThresholdSettings(link_score=True))
    assert _scores(engine, crawl_id, base_url)["/"] == 100
