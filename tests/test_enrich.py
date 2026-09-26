"""Enrichers (issue #19): plugins are found through entry points, their metrics land in url_metrics
and show up in `spider url`."""

from __future__ import annotations

import importlib
import json
import sys
import textwrap
from pathlib import Path

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import enrich, maintenance, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.errors import InvalidArguments, ProviderError
from rb_spider.core.settings import CrawlSettings, Settings

from . import polygon

# The stub plugin package: `clicks` gives every crawled URL a number, `broken` can't be imported,
# `failing` raises halfway (when STUB_FAIL is set).
STUB = """
import os
from rb_spider.core.enrich import Metric

class Clicks:
    description = "Тестовая заглушка: клики по URL"

    def enrich(self, crawl):
        for i, url in enumerate(crawl.urls()):
            yield Metric(url, "clicks", value=i + 1)
        yield Metric(crawl.start_url, "query", text="купить слона")
        if os.environ.get("STUB_FAIL"):
            raise ConnectionError("API is down")
"""


@pytest.fixture
def stub_plugin(tmp_path: Path, monkeypatch):
    """Install a real (on sys.path) distribution with entry points in the `rb_spider.enrichers` group."""
    (tmp_path / "spider_stub_enricher.py").write_text(textwrap.dedent(STUB), encoding="utf-8")
    dist = tmp_path / "spider_stub_enricher-0.1.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: spider-stub-enricher\nVersion: 0.1\n")
    (dist / "entry_points.txt").write_text(
        "[rb_spider.enrichers]\nclicks = spider_stub_enricher:Clicks\nbroken = spider_no_such_module:Thing\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    yield
    sys.modules.pop("spider_stub_enricher", None)


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture
def crawl(base_url: str):
    with storage.database() as engine:
        result = crawl_site(engine, f"{base_url}/", "polygon", Settings(crawl=CrawlSettings(max_urls=5)))
        yield engine, result.crawl_id


def _json(*args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(app, ["--json", *args])
    return result.exit_code, json.loads(result.stdout)


def test_plugins_are_discovered_through_entry_points(stub_plugin) -> None:
    code, data = _json("enrichers")
    assert code == 0
    found = {p["name"]: p for p in data["enrichers"]}
    assert found["clicks"]["description"] == "Тестовая заглушка: клики по URL" and found["clicks"]["error"] is None
    assert "ModuleNotFoundError" in found["broken"]["error"]  # listed with the reason, doesn't break spider


def test_enrich_stores_metrics_visible_in_spider_url(stub_plugin, crawl, base_url: str) -> None:
    engine, crawl_id = crawl
    code, data = _json("enrich", "--plugin", "clicks")
    assert code == 0 and data == {"ok": True, "crawl_id": crawl_id, "stored": {"clicks": 6}}  # 5 URLs + a text

    code, page = _json("url", f"{base_url}/")
    assert {(m["source"], m["name"]) for m in page["metrics"]} == {("clicks", "clicks"), ("clicks", "query")}
    assert next(m for m in page["metrics"] if m["name"] == "query")["text"] == "купить слона"

    _json("enrich", "--plugin", "clicks")  # a re-run replaces, doesn't add
    with engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(storage.url_metrics)).scalar_one() == 6

    maintenance.delete_crawls(engine, maintenance.select_crawls(engine, [crawl_id]))  # metrics go with the crawl
    with engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(storage.url_metrics)).scalar_one() == 0


def test_a_failing_plugin_keeps_its_old_metrics(stub_plugin, crawl, monkeypatch) -> None:
    engine, crawl_id = crawl
    enrich.run(engine, crawl_id, ["clicks"])
    monkeypatch.setenv("STUB_FAIL", "1")
    code, data = _json("enrich", "--plugin", "clicks")
    assert code == 5 and data["error"]["provider"] == "clicks" and "API is down" in data["error"]["message"]
    with engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(storage.url_metrics)).scalar_one() == 6


def test_unknown_or_broken_plugin(stub_plugin, crawl) -> None:
    engine, crawl_id = crawl
    with pytest.raises(InvalidArguments, match="Unknown enricher: nope"):
        enrich.run(engine, crawl_id, ["nope"])
    with pytest.raises(ProviderError, match="cannot be loaded"):
        enrich.run(engine, crawl_id, ["broken"])
    assert enrich.run(engine, crawl_id) == {"clicks": 6}  # "all" skips what can't be loaded


def test_bad_metrics_are_rejected(crawl, monkeypatch) -> None:
    engine, crawl_id = crawl

    class Bad:
        description = ""

        def enrich(self, crawl):
            yield enrich.Metric("https://s.ex/", "speed", value=float("nan"))

    plugin = enrich.Plugin("bad", "x:Bad", "", None, Bad())
    monkeypatch.setattr(enrich, "discover", lambda: [plugin])
    with pytest.raises(ProviderError, match="non-numeric"):
        enrich.run(engine, crawl_id)


def test_no_plugins_installed(crawl) -> None:
    code, data = _json("enrichers")
    assert code == 0 and all(p["name"] not in ("clicks", "broken") for p in data["enrichers"])
