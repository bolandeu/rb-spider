"""JavaScript raw vs rendered (#39): every JavaScript rule finds its trap in a rendered crawl of /js/, and what the
browser saw — console, blocked resources, JS redirects, shadow DOM, iframes, window size — is stored."""

from __future__ import annotations

import importlib.util
import json

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import issues, storage
from rb_spider.core.crawl import AutoRender, crawl_site
from rb_spider.core.settings import CrawlSettings, Settings

from . import polygon
from .conftest import db_env

needs_playwright = pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None, reason="the `render` extra is not installed"
)


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture
def engine():
    with storage.database() as engine:
        yield engine


def _settings(**crawl) -> Settings:
    return Settings(crawl=CrawlSettings(render_tabs=4, **crawl))


@pytest.fixture(scope="module")
def rendered(base_url: str):
    """One rendered crawl of the JavaScript traps, shared by the tests below."""
    with storage.database() as engine:
        yield engine, crawl_site(engine, f"{base_url}/js/", "polygon", _settings(render="always")).crawl_id


def _pages(engine, crawl_id: int, base_url: str) -> dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(sa.select(storage.pages).where(storage.pages.c.crawl_id == crawl_id)).mappings()
        return {row["url"].removeprefix(base_url): dict(row) for row in rows}


@needs_playwright
@pytest.mark.parametrize("code", sorted(polygon.JS_EXPECTED))
def test_javascript_rule_finds_exactly_its_trap(code: str, base_url: str, rendered) -> None:
    engine, crawl_id = rendered
    _, rows = issues.urls_with(engine, crawl_id, code)
    assert {row["url"].removeprefix(base_url) for row in rows} == polygon.JS_EXPECTED[code]


@needs_playwright
def test_raw_and_rendered_values_are_both_kept(base_url: str, rendered) -> None:
    engine, crawl_id = rendered
    pages = _pages(engine, crawl_id, base_url)
    page = pages["/js/title-updated"]
    assert page["raw_title"] == polygon.TITLE.format("js-title-updated")
    assert page["title"] == polygon.TITLE.format("js-title-updated, новый")
    assert pages["/js/noindex"]["raw_directives"] == ",noindex," and pages["/js/noindex"]["indexable"]
    assert pages["/js/content"]["word_count"] - pages["/js/content"]["raw_word_count"] == 30


@needs_playwright
def test_js_redirect_is_a_redirect_and_its_target_is_crawled(base_url: str, rendered) -> None:
    engine, crawl_id = rendered
    pages = _pages(engine, crawl_id, base_url)
    source = pages["/js/redirect"]
    assert source["refresh_kind"] == "javascript" and source["refresh_url"] == f"{base_url}/js/landing"
    assert source["indexability_status"] == "Redirected"
    assert source["title"] == polygon.TITLE.format("js-redirect")  # the page's own (raw) data
    assert pages["/js/landing"]["status_code"] == 200


@needs_playwright
def test_shadow_dom_and_iframes_are_flattened(base_url: str, rendered) -> None:
    engine, crawl_id = rendered
    pages = _pages(engine, crawl_id, base_url)
    assert "/js/shadow-target" in pages and "/js/frame-target" in pages
    with engine.connect() as conn:
        origins = dict(conn.execute(sa.text(
            "SELECT target, origin FROM links WHERE crawl_id = :c AND source = :s AND kind = 'hyperlink'"),
            {"c": crawl_id, "s": f"{base_url}/js/links"}).all())  # fmt: skip
    assert origins == {f"{base_url}/js/": "html & rendered", f"{base_url}/js/linked": "rendered"}


@needs_playwright
def test_flattening_can_be_turned_off(base_url: str, engine) -> None:
    settings = _settings(render="always", render_flatten_shadow_dom=False, render_flatten_iframes=False, max_depth=1)
    crawl_id = crawl_site(engine, f"{base_url}/js/shadow", "polygon", settings).crawl_id
    assert "/js/shadow-target" not in _pages(engine, crawl_id, base_url)


@needs_playwright
def test_console_and_blocked_resources_are_reported(base_url: str, rendered) -> None:
    engine, crawl_id = rendered

    def report(*args: str) -> dict:
        result = CliRunner().invoke(app, ["--json", "report", "javascript", str(crawl_id), *args],
                                    env=db_env(engine))  # fmt: skip
        assert result.exit_code == 0, result.stdout
        return json.loads(result.stdout)

    console = report()
    messages = {row["message"] for row in console["rows"]}
    assert "polygon: broken widget" in messages and any("undefinedFunction" in m for m in messages)
    rows = report("--only", "resources")["rows"]
    assert {(r["resource"], r["kind"], r["reason"]) for r in rows} >= {
        (f"{base_url}/private/app.js", "blocked", "robots.txt")
    }
    assert report("--url", f"{base_url}/js/errors")["total"] == 2


@needs_playwright
def test_viewport_sets_the_window_size(base_url: str, engine) -> None:
    for viewport, width in (("mobile", 411), ("800x600", 800)):
        settings = _settings(render="always", render_viewport=viewport, max_depth=0)
        crawl_id = crawl_site(engine, f"{base_url}/js/viewport", "polygon", settings).crawl_id
        assert _pages(engine, crawl_id, base_url)["/js/viewport"]["title"] == f"width {width}"


@needs_playwright
def test_render_auto_stops_when_javascript_changes_nothing(base_url: str, engine) -> None:
    settings = _settings(render="auto", render_auto_sample=2, max_urls=8, concurrency=1)
    pages = _pages(engine, crawl_site(engine, f"{base_url}/a", "polygon", settings).crawl_id, base_url)
    html = [p for p in pages.values() if p["status_code"] == 200 and "html" in (p["content_type"] or "")]
    assert sum(p["rendered"] is True for p in html) == 2 and len(html) > 2


@needs_playwright
def test_render_auto_keeps_rendering_when_javascript_matters(base_url: str, engine) -> None:
    settings = _settings(render="auto", render_auto_sample=1, max_depth=1)
    pages = _pages(engine, crawl_site(engine, f"{base_url}/js-only", "polygon", settings).crawl_id, base_url)
    assert pages["/js-only"]["rendered"] and pages["/js-target"]["rendered"]  # found only through the JS link


def test_auto_render_decision() -> None:
    auto = AutoRender("auto", 2)
    assert [auto.wanted() for _ in range(3)] == [True, True, False]
    auto.seen(True)
    assert auto.wanted()
    assert not AutoRender("never", 5).wanted() and AutoRender("always", 0).wanted()


def test_javascript_rules_are_not_checked_without_rendering(base_url: str, engine) -> None:
    crawl_id = crawl_site(engine, f"{base_url}/js/", "polygon", _settings(max_depth=0)).crawl_id
    skipped = {rule.code: rule.requires for rule in issues.not_checked(engine, crawl_id)}
    assert skipped["js_title_updated"] == ("crawl.render!=never",)
    assert "js_ajax_meta_fragment" not in skipped  # needs no browser


# --- images (#40) ------------------------------------------------------------------


@needs_playwright
def test_background_images_from_stylesheets_are_found_when_rendered(base_url: str, rendered) -> None:
    engine, crawl_id = rendered
    with engine.connect() as conn:
        rows = conn.execute(sa.text(
            "SELECT target, origin FROM links WHERE crawl_id = :c AND source = :s AND kind = 'image'"),
            {"c": crawl_id, "s": f"{base_url}/js/images"}).all()  # fmt: skip
    assert set(rows) == {(f"{base_url}/img/hero.png", "css background"), (f"{base_url}/img/real.png", None)}


@needs_playwright
def test_incorrectly_sized_images_need_images_loaded(base_url: str, engine) -> None:
    settings = _settings(render="always", render_images=True, max_depth=1)
    crawl_id = crawl_site(engine, f"{base_url}/js/images", "polygon", settings).crawl_id
    _, rows = issues.urls_with(engine, crawl_id, "images_incorrectly_sized")
    assert [(row["url"], row["detail"]) for row in rows] == [
        (f"{base_url}/img/real.png", f"800×600 → 100×75, {base_url}/js/images")
    ]
    runner = CliRunner()
    result = runner.invoke(app, ["--json", "url", f"{base_url}/js/images", "--crawl", str(crawl_id)],
                           env=db_env(engine))  # fmt: skip
    [image] = [r for r in json.loads(result.stdout)["resources"] if r["target"].endswith("/img/real.png")]
    assert (image["real_width"], image["real_height"], image["display_width"], image["display_height"]) == (
        800, 600, 100, 75)  # fmt: skip


@needs_playwright
def test_without_render_images_sizes_are_not_checked(base_url: str, rendered) -> None:
    engine, crawl_id = rendered
    assert "images_incorrectly_sized" in {rule.code for rule in issues.not_checked(engine, crawl_id)}
    pages = _pages(engine, crawl_id, base_url)
    assert (pages["/img/real.png"]["image_width"], pages["/img/real.png"]["image_height"]) == (800, 600)


# --- screenshots (v3) --------------------------------------------------------------


@needs_playwright
def test_screenshots_are_files_that_go_with_their_crawl(base_url: str, engine) -> None:
    from pathlib import Path

    from rb_spider.core import maintenance

    settings = _settings(render="always", render_screenshots=True, max_depth=0)
    crawl_id = crawl_site(engine, f"{base_url}/js/viewport", "polygon", settings).crawl_id
    shot = Path(_pages(engine, crawl_id, base_url)["/js/viewport"]["screenshot"])
    assert shot.read_bytes()[:2] == b"\xff\xd8" and shot.parent == storage.screenshots_dir(crawl_id)  # a JPEG
    maintenance.delete_crawls(engine, [storage.get_crawl(engine, crawl_id)[0]])
    assert not shot.parent.exists()


# --- View Source, screenshot export (#51) ------------------------------------------


@needs_playwright
def test_view_source_raw_rendered_and_diff(base_url: str, engine, monkeypatch, tmp_path) -> None:
    from .conftest import use_db

    settings = _settings(render="always", store_html=True, render_screenshots=True, max_depth=0)
    crawl_id = crawl_site(engine, f"{base_url}/js/title-updated", "polygon", settings).crawl_id
    use_db(monkeypatch, engine)
    runner = CliRunner()

    def run(*args: str) -> dict:
        result = runner.invoke(app, ["--json", *args])
        assert result.exit_code == 0, result.stdout
        return json.loads(result.stdout)

    url = f"{base_url}/js/title-updated"
    raw = run("source", url)["html"]
    rendered = run("source", url, "--rendered")["html"]
    assert polygon.TITLE.format("js-title-updated") in raw and "новый" not in raw.split("<script>")[0]
    assert polygon.TITLE.format("js-title-updated, новый") in rendered
    diff = run("source", url, "--diff")
    assert any(line.startswith("+") and "новый" in line for line in diff["diff"])

    exported = runner.invoke(app, ["export", "rendered-source", "--crawl", str(crawl_id)])
    assert "новый" in exported.stdout
    folder = tmp_path / "shots"
    data = run("export", "screenshots", "--crawl", str(crawl_id), "-o", str(folder))
    assert data["rows"] == 1 and (folder / "index.csv").read_text().count("\n") == 2
    [shot] = folder.glob("*.jpg")
    assert shot.read_bytes()[:2] == b"\xff\xd8"


def test_view_source_needs_stored_html(base_url: str, engine, monkeypatch) -> None:
    from .conftest import use_db

    crawl_site(engine, f"{base_url}/a", "polygon", _settings(max_depth=0))
    use_db(monkeypatch, engine)
    result = CliRunner().invoke(app, ["--json", "source", f"{base_url}/a"])
    assert result.exit_code == 2 and "--store-html" in json.loads(result.stdout)["error"]["message"]
