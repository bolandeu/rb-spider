"""Custom Search, Custom Extraction and link positions (#36) on the polygon's /cx page."""

from __future__ import annotations

import importlib.util
import json

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import crawl as crawl_module
from rb_spider.core import custom_report, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.settings import (
    CollectSettings,
    CrawlSettings,
    CustomExtract,
    CustomSearch,
    CustomSettings,
    Settings,
)

from . import polygon

SEARCH = [
    CustomSearch(name="GTM", query="googletagmanager.com"),
    CustomSearch(name="promo", query="акция", scope="text"),
    CustomSearch(name="price-digits", query=r"\d+", regex=True, scope="element", selector=".price"),
    CustomSearch(name="nothing", query="lorem-nope"),
]
EXTRACT = [
    CustomExtract(name="price", query=".price", limit=5),
    CustomExtract(name="author", query='meta[name="author"]', output="content"),
    CustomExtract(name="sku", kind="regex", query=r"SKU-(\d+)"),
    CustomExtract(name="menu", query="nav.main-menu", output="inner_html"),
]
needs_lxml = pytest.mark.skipif(importlib.util.find_spec("lxml") is None, reason="extra rb-spider[xpath]")


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


def _crawl(base_url: str, **kwargs) -> tuple[sa.Engine, int]:
    settings = Settings(crawl=CrawlSettings(max_depth=0), **kwargs)
    engine = storage.open_db()
    return engine, crawl_site(engine, f"{base_url}/cx", "polygon", settings).crawl_id


def _values(engine: sa.Engine, crawl_id: int) -> dict[tuple[str, str], list]:
    found: dict[tuple[str, str], list] = {}
    with engine.connect() as conn:
        rows = conn.execute(sa.select(storage.custom_values).where(storage.custom_values.c.crawl_id == crawl_id)
                            .order_by(storage.custom_values.c.n))  # fmt: skip
        for row in rows:
            found.setdefault((row.kind, row.name), []).append(row.value if row.kind == "extract" else row.n)
    return found


def test_search_and_extract(base_url: str) -> None:
    engine, crawl_id = _crawl(base_url, custom=CustomSettings(search=SEARCH, extract=EXTRACT))
    values = _values(engine, crawl_id)
    assert values[("search", "GTM")] == [1]
    assert values[("search", "promo")] == [2]  # text, case-insensitive
    assert values[("search", "price-digits")] == [4]  # 1, 990, 2, 490
    assert ("search", "nothing") not in values
    assert values[("extract", "price")] == ["1 990 ₽", "2 490 ₽"]
    assert values[("extract", "author")] == ["Редакция"]
    assert values[("extract", "sku")] == ["12345"]
    assert values[("extract", "menu")][0].startswith('<ul><li><a href="/b">')
    rules = {r["name"]: r for r in custom_report.rules(engine, crawl_id)}
    assert (rules["GTM"]["pages"], rules["nothing"]["without"], rules["price"]["without"]) == (1, 1, None)
    engine.dispose()


@needs_lxml
def test_xpath_extraction(base_url: str) -> None:
    extract = [CustomExtract(name="h1", kind="xpath", query="//h1"), CustomExtract(name="n", kind="xpath",
               query="count(//a)"), CustomExtract(name="hrefs", kind="xpath", query="//nav//a/@href", limit=5)]  # fmt: skip
    engine, crawl_id = _crawl(base_url, custom=CustomSettings(extract=extract))
    values = _values(engine, crawl_id)
    assert values[("extract", "h1")] == ["Товар дня"] and values[("extract", "n")] == ["6.0"]
    assert values[("extract", "hrefs")] == ["/b", "/c"]
    engine.dispose()


def test_link_positions_and_paths(base_url: str) -> None:
    engine, crawl_id = _crawl(base_url, collect=CollectSettings(link_path=True))
    with engine.connect() as conn:
        rows = conn.execute(sa.select(storage.links.c.anchor, storage.links.c.position, storage.links.c.path).where(
            storage.links.c.crawl_id == crawl_id, storage.links.c.kind == "hyperlink")).all()  # fmt: skip
    engine.dispose()
    by_anchor = {anchor: (position, path) for anchor, position, path in rows}
    assert by_anchor["Главная раздела"] == ("header", "/header.site-header")
    assert by_anchor["Каталог"][0] == by_anchor["Доставка"][0] == "nav"
    assert by_anchor["В магазин"] == ("content", "/main")
    assert by_anchor["Похожее"][0] == "sidebar" and by_anchor["Контакты"][0] == "footer"


def test_positions_are_rules(base_url: str) -> None:
    custom = CustomSettings(link_positions=[("price", "offers")])
    engine, crawl_id = _crawl(base_url, custom=custom)
    with engine.connect() as conn:
        positions = set(conn.execute(sa.select(storage.links.c.position).where(
            storage.links.c.crawl_id == crawl_id, storage.links.c.kind == "hyperlink")).scalars())  # fmt: skip
    engine.dispose()
    assert positions == {"content"}  # no "nav" rule any more; no link sits in .price


def test_cli_custom(base_url: str) -> None:
    runner = CliRunner()
    rules = json.dumps([{"name": "GTM", "query": "googletagmanager"}, {"name": "none", "query": "zzz"}])
    args = [
        "--json",
        "crawl",
        f"{base_url}/cx",
        "--max-depth",
        "1",
        "--set",
        f"custom.search={rules.replace(':', '=')}",
    ]
    assert runner.invoke(app, args).exit_code == 0, "crawl"
    data = json.loads(runner.invoke(app, ["--json", "custom"]).stdout)
    assert {r["name"]: r["pages"] for r in data["rules"]} == {"GTM": 1, "none": 0}
    without = json.loads(runner.invoke(app, ["--json", "custom", "--search", "GTM", "--without"]).stdout)
    assert without["total"] >= 1 and all(not r["url"].endswith("/cx") for r in without["rows"])
    assert runner.invoke(app, ["--json", "custom", "--extract", "x", "--without"]).exit_code == 2
    assert "GTM" in runner.invoke(app, ["custom"]).stdout


def test_bad_rules_are_refused() -> None:
    with pytest.raises(ValidationError, match="invalid regular expression"):
        CustomSearch(name="x", query="(", regex=True)
    with pytest.raises(ValidationError, match="needs a selector"):
        CustomSearch(name="x", query="a", scope="element")


def test_xpath_without_lxml_is_refused(base_url: str, monkeypatch) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(crawl_module.importlib.util, "find_spec", lambda name: None if name == "lxml" else real(name))
    rules = '[{name="h", kind="xpath", query="//h1"}]'
    result = CliRunner().invoke(app, ["--json", "crawl", f"{base_url}/cx", "--set", f"custom.extract={rules}"])
    assert result.exit_code == 1 and json.loads(result.stdout)["error"]["code"] == "XPATH_UNAVAILABLE"
