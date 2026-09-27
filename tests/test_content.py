"""Content (#30): near duplicates, Duplicate Details, the duplicate settings, readability and text ratio."""

from __future__ import annotations

import importlib.util
import json

import pytest
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import content, issues, storage
from rb_spider.core import crawl as crawl_module
from rb_spider.core.crawl import crawl_site
from rb_spider.core.settings import CollectSettings, CrawlSettings, Settings, ThresholdSettings

from . import polygon
from .conftest import use_db

needs_datasketch = pytest.mark.skipif(importlib.util.find_spec("datasketch") is None, reason="extra rb-spider[near]")


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture(scope="module")
def near_crawl(base_url: str):
    settings = Settings(collect=CollectSettings(near_duplicates=True), crawl=CrawlSettings(store_html=True))
    with storage.database() as engine:
        yield engine, crawl_site(engine, f"{base_url}/", "polygon", settings).crawl_id


def _paths(rows: list[dict], base_url: str, key: str = "url") -> set[str]:
    return {row[key].removeprefix(base_url) for row in rows}


@needs_datasketch
def test_near_duplicates_rule(base_url: str, near_crawl) -> None:
    engine, crawl_id = near_crawl
    _, rows = issues.urls_with(engine, crawl_id, "content_near_duplicates")
    assert _paths(rows, base_url) == polygon.NEAR_DUPLICATES
    near_1 = next(row for row in rows if row["url"].endswith("/near-1"))
    assert near_1["detail"].startswith("1 почти-дубл., ближайший ") and near_1["detail"].endswith("/near-2")


@needs_datasketch
def test_duplicate_details_and_diff(base_url: str, near_crawl, monkeypatch) -> None:
    from rb_spider.core import duplicates

    engine, crawl_id = near_crawl
    use_db(monkeypatch, engine)  # the shared crawl's stored HTML lives beside it
    total, pairs = duplicates.report(engine, crawl_id, ThresholdSettings(), kind="near", url=f"{base_url}/near-1")
    assert total == 1 and 0.9 <= pairs[0]["similarity"] < 1
    diff = duplicates.text_diff(crawl_id, pairs[0]["url"], pairs[0]["other"])
    assert diff and any(line.startswith("-") and "слово7" in line for line in diff)
    _, exact = duplicates.report(engine, crawl_id, ThresholdSettings(), kind="exact")
    assert {(p["url"].removeprefix(base_url), p["other"].removeprefix(base_url)) for p in exact} == {
        ("/dup-4", "/dup-3")
    }


@needs_datasketch
def test_higher_similarity_threshold_drops_pairs(base_url: str, near_crawl) -> None:
    engine, crawl_id = near_crawl
    try:
        issues.analyze(engine, crawl_id, ThresholdSettings(near_duplicate_similarity=100))
        _, rows = issues.urls_with(engine, crawl_id, "content_near_duplicates")
        assert "/near-1" not in _paths(rows, base_url) and "/dup-3" in _paths(rows, base_url)
    finally:
        issues.analyze(engine, crawl_id)


@needs_datasketch
def test_cli_duplicates(base_url: str) -> None:
    runner = CliRunner()
    args = ["--json", "crawl", f"{base_url}/", "--set", "collect.near_duplicates=true"]
    assert runner.invoke(app, args).exit_code == 0
    data = json.loads(runner.invoke(app, ["--json", "duplicates", "--url", f"{base_url}/near-2", "--diff"]).stdout)
    assert data["total"] == 1 and data["pairs"][0]["diff"] is None  # no --store-html: nothing to diff
    assert runner.invoke(app, ["--json", "duplicates", "--diff"]).exit_code == 2


def test_indexable_only_off_counts_canonicalised_copies(base_url: str) -> None:
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/", "polygon").crawl_id
        issues.analyze(engine, crawl_id, ThresholdSettings(duplicates_indexable_only=False))
        _, rows = issues.urls_with(engine, crawl_id, "content_exact_duplicates")
    assert {"/dup-1", "/dup-2", "/dup-3", "/dup-4"} <= _paths(rows, base_url)


def test_soft_404_patterns_are_settings(base_url: str) -> None:
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/", "polygon").crawl_id
        issues.analyze(engine, crawl_id, ThresholdSettings(soft_404_patterns=["полигон spider: страница a "]))
        _, rows = issues.urls_with(engine, crawl_id, "content_soft_404")
    assert _paths(rows, base_url) == {"/a"}


def test_near_duplicates_without_the_extra_is_refused(base_url: str, monkeypatch) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(
        crawl_module.importlib.util, "find_spec", lambda name: None if name == "datasketch" else real(name)
    )
    result = CliRunner().invoke(app, ["--json", "crawl", f"{base_url}/", "--set", "collect.near_duplicates=true"])
    assert result.exit_code == 1 and json.loads(result.stdout)["error"]["code"] == "NEAR_DUPLICATES_UNAVAILABLE"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The cat sat on the mat. It was a sunny day.", (109.0, 5.5)),
        ("Мы долго обсуждали правила работы и решили сменить порядок проверки всех документов.", (41.0, 12.0)),
        ("123 456 — …", None),
    ],
)
def test_readability(text: str, expected: tuple[float, float] | None) -> None:
    assert content.readability(text) == expected


def test_bands_cover_the_threshold() -> None:
    for threshold in (0.5, 0.8, 0.9, 1.0):
        bands, rows = content.bands_for(threshold)
        assert bands * rows <= content.NUM_PERM
        assert (1 / bands) ** (1 / rows) <= threshold  # pairs at the threshold are likely candidates
