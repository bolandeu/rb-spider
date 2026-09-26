"""Structured data (#31): a crawl of the polygon's /sd/ folder with every format collected."""

from __future__ import annotations

import importlib.util
import json
from typing import Literal

import pytest
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import crawl as crawl_module
from rb_spider.core import issues, storage, structured
from rb_spider.core.crawl import crawl_site
from rb_spider.core.settings import CollectSettings, CrawlSettings, Settings

from . import polygon

pytestmark = pytest.mark.skipif(importlib.util.find_spec("extruct") is None, reason="extra rb-spider[structured]")
ALL: list[Literal["json-ld", "microdata", "rdfa"]] = ["json-ld", "microdata", "rdfa"]


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


def _settings(**crawl) -> Settings:
    return Settings(collect=CollectSettings(structured_data=ALL),
                    crawl=CrawlSettings(stay_in_start_folder=True, check_outside_start_folder=False, **crawl))  # fmt: skip


@pytest.fixture(scope="module")
def sd_crawl(base_url: str):
    with storage.database() as engine:
        yield engine, crawl_site(engine, f"{base_url}/sd/", "polygon", _settings()).crawl_id


@pytest.mark.parametrize("code", sorted(polygon.STRUCTURED_EXPECTED))
def test_structured_rules(code: str, base_url: str, sd_crawl) -> None:
    engine, crawl_id = sd_crawl
    _, rows = issues.urls_with(engine, crawl_id, code)
    assert {row["url"].removeprefix(base_url) for row in rows} == polygon.STRUCTURED_EXPECTED[code]


def test_validation_messages(base_url: str, sd_crawl) -> None:
    engine, crawl_id = sd_crawl
    with engine.connect() as conn:
        rows = structured.summary(conn, crawl_id, "validation")
    texts = {(r["severity"], r["scope"], r["message"]) for r in rows}
    assert ("error", "schema.org", "свойства colour нет в Schema.org") in texts
    assert ("error", "schema.org", "тип Departmentt не существует в Schema.org") in texts
    assert ("warning", "schema.org", "свойство branchOf устарело (superseded)") in texts
    assert ("warning", "schema.org", "data-vocabulary.org устарел: используйте schema.org") in texts
    assert ("error", "google", "Event: нет обязательного свойства startDate") in texts
    assert all(r["urls"] >= 1 and r["example"].startswith(base_url) for r in rows)
    assert [r["severity"] for r in rows] == sorted((r["severity"] for r in rows), key=["error", "warning"].index)


def test_features_and_overview_counts(sd_crawl) -> None:
    engine, crawl_id = sd_crawl
    with engine.connect() as conn:
        features = {r["feature"]: r for r in structured.summary(conn, crawl_id, "features")}
        counts = structured.counts(conn, crawl_id)
    assert features["Product"]["urls"] == 2 and features["Product"]["with_warnings"] == 1  # /sd/ok is complete
    assert features["Event"]["with_errors"] == 1
    assert counts == {"contains": 7, "missing": 1, "json-ld": 5, "microdata": 2, "rdfa": 1}


def test_url_shows_messages_and_items_with_stored_html(base_url: str, monkeypatch) -> None:
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/sd/", "polygon", _settings(store_html=True)).crawl_id
    runner = CliRunner()
    data = json.loads(runner.invoke(app, ["--json", "url", f"{base_url}/sd/invalid", "--crawl", str(crawl_id)]).stdout)
    assert data["page"]["sd_errors"] == 2 and data["page"]["sd_types"] == ",Organization,Departmentt,"
    assert data["page"]["sd_messages"][0][4] == "свойства colour нет в Schema.org"
    assert data["structured_data"][0]["@type"] == "Organization"
    out = runner.invoke(app, ["url", f"{base_url}/sd/invalid", "--crawl", str(crawl_id)]).stdout
    assert "Микроразметка" in out and "colour" in out


def test_cli_structured_report(base_url: str) -> None:
    runner = CliRunner()
    args = ["--json", "crawl", f"{base_url}/sd/", "--set", 'collect.structured_data=["json-ld"]']
    assert runner.invoke(app, args).exit_code == 0
    data = json.loads(runner.invoke(app, ["--json", "structured", "--report", "features"]).stdout)
    assert {r["feature"] for r in data["rows"]} >= {"Product", "Event", "Organization"}
    assert runner.invoke(app, ["structured"]).exit_code == 0


def test_microdata_without_extruct_is_refused(base_url: str, monkeypatch) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(
        crawl_module.importlib.util, "find_spec", lambda name: None if name == "extruct" else real(name)
    )
    args = ["--json", "crawl", f"{base_url}/sd/", "--set", 'collect.structured_data=["microdata"]']
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 1 and json.loads(result.stdout)["error"]["code"] == "STRUCTURED_DATA_UNAVAILABLE"
