"""JS rendering (issue #15): with crawl.render = "always" content that only JS creates is extracted."""

from __future__ import annotations

import importlib.util
import json

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import render, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.errors import RenderUnavailable
from rb_spider.core.settings import CrawlSettings, Settings

from . import polygon

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


def _pages(engine, crawl_id: int) -> dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(sa.select(storage.pages).where(storage.pages.c.crawl_id == crawl_id)).mappings()
        return {row["url"]: dict(row) for row in rows}


def _crawl(engine, base_url: str, mode: str) -> dict[str, dict]:
    settings = Settings(crawl=CrawlSettings(render=mode, max_depth=1, render_tabs=2))  # ty: ignore[invalid-argument-type]
    return _pages(engine, crawl_site(engine, f"{base_url}/js-only", "polygon", settings).crawl_id)


def test_without_rendering_js_content_is_invisible(base_url: str, engine) -> None:
    pages = _crawl(engine, base_url, "never")
    page = pages[f"{base_url}/js-only"]
    assert page["title"] is None and page["h1"] is None and page["rendered"] is None
    assert f"{base_url}/js-target" not in pages


@needs_playwright
def test_rendering_extracts_js_title_h1_and_links(base_url: str, engine) -> None:
    pages = _crawl(engine, base_url, "always")
    page = pages[f"{base_url}/js-only"]
    assert page["rendered"] is True
    assert page["title"] == "Заголовок из JS" and page["h1"] == "H1 из JS"
    assert page["bytes"] < 1000  # the response's size, not the DOM's
    target = pages[f"{base_url}/js-target"]  # found only through the JS link
    assert target["status_code"] == 200 and target["rendered"] is True


def test_without_playwright_a_clear_error(base_url: str, monkeypatch) -> None:
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a: None if name == "playwright" else real_find_spec(name, *a)
    )
    with pytest.raises(RenderUnavailable):
        render.ensure_available()
    result = CliRunner().invoke(app, ["--json", "crawl", f"{base_url}/js-only", "--render", "always"])
    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "RENDER_UNAVAILABLE" and "render_browser" in error["action"]


@needs_playwright
def test_a_browser_that_cannot_start_fails_the_crawl_up_front(base_url: str, engine, monkeypatch) -> None:
    from crawlee.browsers import BrowserPool

    async def broken(*_args, **_kwargs):
        raise RuntimeError("Executable doesn't exist at /nowhere/chrome")

    monkeypatch.setattr(BrowserPool, "new_page", broken)
    with pytest.raises(RenderUnavailable, match="no browser could start"):  # not a crawl of "dead" pages
        _crawl(engine, base_url, "always")


def test_cached_browsers_newest_first_headless_shell_first(tmp_path) -> None:
    for build, exe in [("chromium-1200", "chrome-linux/chrome"), ("chromium_headless_shell-1228", "shell/chrome-headless-shell"),
                       ("chromium-1228", "chrome-linux/chrome"), ("ffmpeg-1011", "ffmpeg"), ("chromium-1300", "empty/readme")]:  # fmt: skip
        path = tmp_path / build / exe
        path.parent.mkdir(parents=True)
        path.write_text("")
    found = [str(p.relative_to(tmp_path)) for p in render.cached_browsers(tmp_path)]
    assert found == [
        "chromium_headless_shell-1228/shell/chrome-headless-shell",
        "chromium-1228/chrome-linux/chrome",
        "chromium-1200/chrome-linux/chrome",
    ]  # a build without an executable is skipped


@needs_playwright
def test_explicit_browser_path_that_does_not_exist(base_url: str, engine) -> None:
    settings = Settings(crawl=CrawlSettings(render="always", render_browser="/nowhere/chrome"))
    with pytest.raises(RenderUnavailable, match="/nowhere/chrome"):
        crawl_site(engine, f"{base_url}/js-only", "polygon", settings)
