"""SERP (#33): pixel widths in Arial, truncation, the snippet in `spider url`, summary and preview."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import issues, serp, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.settings import ThresholdSettings

from . import polygon


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


def _json(*args: str) -> dict:
    result = CliRunner().invoke(app, ["--json", *args])
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def test_width_follows_arial() -> None:
    assert serp.width("", 20) == 0
    assert serp.width("iiii", 20) < serp.width("WWWW", 20)  # proportional, not characters
    assert serp.width("Ш", 20) == serp.width("Ш", 40) // 2
    assert serp.width("😀", 20) == serp.width("W", 20)  # outside the table: a wide character


def test_truncate_cuts_at_a_word() -> None:
    text = "Купить угловой диван в Москве недорого — каталог мебели с доставкой и сборкой"
    shown, cut = serp.truncate(text, 561, 20)
    assert cut and shown == "Купить угловой диван в Москве недорого — каталог …"
    assert serp.width(shown, 20) <= 561
    assert serp.truncate("Коротко", 561, 20) == ("Коротко", False)
    assert serp.display_url("https://s.example/%D0%BA%D0%B0%D1%82/a/") == "s.example › кат › a"


def test_url_shows_the_snippet(base_url: str) -> None:
    _json("crawl", f"{base_url}/", "--max-urls", "60")
    data = _json("url", f"{base_url}/t-long")
    snippet = data["serp"]
    assert snippet["title_truncated"] and snippet["title"].endswith("…") and snippet["title_px"] > 561
    assert data["page"]["title_px"] == snippet["title_px"]
    assert "Сниппет в Google" in CliRunner().invoke(app, ["url", f"{base_url}/t-long"]).stdout


def test_summary_and_font_size_threshold(base_url: str) -> None:
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/", "polygon").crawl_id
        total, rows = serp.summary(engine, crawl_id, limit=5)
        assert total > 5 and all({"title_px", "description_px"} <= set(r) for r in rows)
        issues.analyze(engine, crawl_id, ThresholdSettings(serp_title_font_px=40))  # twice as wide: more titles over
        found, _ = issues.urls_with(engine, crawl_id, "page_title_over_px")
    assert found > len(polygon.EXPECTED_ISSUES["page_title_over_px"])


def test_cli_serp_summary_and_preview(base_url: str) -> None:
    _json("crawl", f"{base_url}/", "--max-urls", "10")
    data = _json("serp", "summary", "--limit", "3")
    assert len(data["pages"]) == 3
    preview = _json("serp", "preview", "--title", "Коротко", "--description", "Описание " * 40)
    assert (preview["title_truncated"], preview["description_truncated"]) == (False, True)
    out = CliRunner().invoke(app, ["serp", "preview", "--title", "Очень длинный заголовок " * 5]).stdout
    assert "обрезано: title" in out
