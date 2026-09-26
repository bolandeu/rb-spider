"""Sitemaps (#32): a crawl of the polygon's /sm/ folder reading its sitemaps through rb-sitemap-xml."""

from __future__ import annotations

import importlib.util
import json

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import crawl as crawl_module
from rb_spider.core import issues, sitemaps, storage
from rb_spider.core.crawl import crawl_site, read_url_list
from rb_spider.core.settings import CrawlSettings, Settings, SitemapSettings, ThresholdSettings

from . import polygon

needs_package = pytest.mark.skipif(
    importlib.util.find_spec("rb_sitemap_xml") is None, reason="extra rb-spider[sitemaps]"
)


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


def _settings(**sitemap) -> Settings:
    return Settings(sitemaps=SitemapSettings(crawl=True, **sitemap),
                    crawl=CrawlSettings(stay_in_start_folder=True, check_outside_start_folder=False))  # fmt: skip


@pytest.fixture(scope="module")
def sm_crawl(base_url: str):
    with storage.database() as engine:
        yield engine, crawl_site(engine, f"{base_url}/sm/", "polygon", _settings()).crawl_id


def _thresholds(base_url: str) -> ThresholdSettings:
    """Limits the polygon's small files can cross: pages.xml has 5 URLs and is the largest file."""
    sizes = {path: len(xml.replace("{base}", base_url).encode()) for path, xml in polygon.SITEMAP_FILES.items()}
    second = sorted(sizes.values())[-2]
    return ThresholdSettings(sitemap_max_urls=4, sitemap_max_mb=(second + 1) / 1048576)


@needs_package
@pytest.mark.parametrize("code", sorted(polygon.SITEMAP_EXPECTED))
def test_sitemap_rules(code: str, base_url: str, sm_crawl) -> None:
    engine, crawl_id = sm_crawl
    issues.analyze(engine, crawl_id, _thresholds(base_url))
    _, rows = issues.urls_with(engine, crawl_id, code)
    assert {row["url"].removeprefix(base_url) for row in rows} == polygon.SITEMAP_EXPECTED[code]


@needs_package
def test_default_limits_find_no_big_sitemaps(sm_crawl) -> None:
    engine, crawl_id = sm_crawl
    issues.analyze(engine, crawl_id)
    assert issues.urls_with(engine, crawl_id, "sitemaps_over_max_urls")[0] == 0
    assert issues.urls_with(engine, crawl_id, "sitemaps_over_max_mb")[0] == 0


@needs_package
def test_report_files_urls_and_orphans(base_url: str, sm_crawl) -> None:
    engine, crawl_id = sm_crawl
    _, files = sitemaps.report(engine, crawl_id, "files")
    by_url = {f["url"].removeprefix(base_url): f for f in files}
    assert (by_url["/sm/sitemap.xml"]["kind"], by_url["/sm/sitemap.xml"]["sitemaps"]) == ("sitemapindex", 3)
    assert (by_url["/sm/pages.xml"]["kind"], by_url["/sm/pages.xml"]["urls"]) == ("urlset", 5)
    assert by_url["/sm/gone.xml"]["kind"] is None and "404" in by_url["/sm/gone.xml"]["error"]
    total, urls = sitemaps.report(engine, crawl_id, "urls")
    assert total == 6 and {u["status_code"] for u in urls} == {200}
    _, orphans = sitemaps.report(engine, crawl_id, "orphans")
    assert [o["url"].removeprefix(base_url) for o in orphans] == ["/sm/orphan"]
    with engine.connect() as conn:
        assert sitemaps.counts(conn, crawl_id) == {"files": 4, "urls": 5, "not_in_sitemap": 1, "orphans": 1}
        hreflang = conn.execute(
            sa.select(storage.links.c.source, storage.links.c.hreflang).where(
                storage.links.c.crawl_id == crawl_id, storage.links.c.kind == "hreflang"
            )
        ).all()
    assert hreflang == [(f"{base_url}/sm/a", "ru")]  # from the sitemap's xhtml:link


@needs_package
def test_explicit_sitemap_urls_without_discovery(base_url: str) -> None:
    settings = _settings(discover=False, urls=[f"{base_url}/sm/more.xml"])
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/sm/", "polygon", settings).crawl_id
        total, files = sitemaps.report(engine, crawl_id, "files")
    assert total == 1 and files[0]["url"] == f"{base_url}/sm/more.xml"


@needs_package
def test_build_sitemaps(base_url: str, sm_crawl, tmp_path) -> None:
    engine, crawl_id = sm_crawl
    files, count = sitemaps.build(engine, crawl_id, tmp_path / "a", base_url=base_url, include=set(), lastmod=False,
                                  images=False)  # fmt: skip
    text = files[0].read_text()
    assert count == 5 and f"<loc>{base_url}/sm/b</loc>" in text and "/sm/noindex" not in text
    files, _ = sitemaps.build(engine, crawl_id, tmp_path / "b", base_url=base_url, include={"noindex"}, lastmod=True,
                              images=False, changefreq="weekly", priority="depth")  # fmt: skip
    text = files[0].read_text()
    assert "/sm/noindex" in text and "<changefreq>weekly</changefreq>" in text
    assert f"<loc>{base_url}/sm/</loc>\n    <changefreq>weekly</changefreq>\n    <priority>1.0</priority>" in text
    for bad in ({"changefreq": "sometimes"}, {"priority": "2"}):
        with pytest.raises(Exception, match="--"):
            sitemaps.build(engine, crawl_id, tmp_path / "d", base_url=base_url, include=set(), lastmod=False,
                           images=False, **bad)  # fmt: skip
    with pytest.raises(Exception, match="unknown"):
        sitemaps.build(engine, crawl_id, tmp_path / "c", base_url=base_url, include={"x"}, lastmod=False, images=False)


@needs_package
def test_cli_sitemaps_show_and_build(base_url: str, tmp_path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["--json", "crawl", f"{base_url}/", "--max-urls", "30"]).exit_code == 0
    out = tmp_path / "out"
    result = runner.invoke(app, ["--json", "sitemaps", "build", "-o", str(out), "--images"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["files"] == [str(out / "image-sitemap.xml")]
    shown = json.loads(runner.invoke(app, ["--json", "sitemaps", "show", "--only", "files"]).stdout)
    assert shown["total"] == 0  # that crawl didn't read sitemaps


def test_sitemaps_without_the_package_are_refused(base_url: str, monkeypatch) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None if name == "rb_sitemap_xml" else real(name))
    result = CliRunner().invoke(app, ["--json", "crawl", f"{base_url}/", "--set", "sitemaps.crawl=true"])
    assert result.exit_code == 1 and json.loads(result.stdout)["error"]["code"] == "SITEMAPS_UNAVAILABLE"
    assert crawl_module.sitemaps is sitemaps


def test_list_file_can_be_a_sitemap_or_csv() -> None:
    xml = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://s.example/a</loc></url>'
           "<url><loc>https://s.example/b</loc></url></urlset>")  # fmt: skip
    assert read_url_list(xml) == ["https://s.example/a", "https://s.example/b"]
    assert read_url_list("Address,Status Code\nhttps://s.example/a,200\n") == ["https://s.example/a"]
    assert read_url_list("https://s.example/q?a=1,2") == ["https://s.example/q?a=1,2"]  # no header: a URL list
    with pytest.raises(Exception, match="sitemap index"):
        read_url_list('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>')
