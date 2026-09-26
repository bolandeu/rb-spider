"""spider fetch / rb_spider.fetch (issue #24): pages without a crawl — redirects, data, Markdown, errors."""

from __future__ import annotations

import importlib.util
import json

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import storage
from rb_spider.core.markdown import html_to_markdown
from rb_spider.fetch import CrawlSettings, FetchResult, fetch, fetch_many

from . import polygon


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


def _lines(*args: str, input: str | None = None) -> tuple[int, list[dict]]:
    result = CliRunner().invoke(app, ["--json", "fetch", *args], input=input)
    return result.exit_code, [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def test_fetch_follows_redirects_and_reports_every_step(base_url: str) -> None:
    page = fetch(f"{base_url}/chain1")
    assert page.final_url == f"{base_url}/a" and page.status == 200
    assert [(r["url"].removeprefix(base_url), r["status"]) for r in page.redirects] == [
        ("/chain1", 301),
        ("/chain2", 302),
    ]
    assert page.seo is not None and "страница a" in page.seo["title"] and page.seo["h1"]
    assert page.links is None and page.text is None and page.html is None  # only what was asked for
    assert page.elapsed_ms is not None and page.bytes


def test_include_adds_links_resources_text_markdown_html(base_url: str) -> None:
    page = fetch(f"{base_url}/i-images", include="headers,links,resources,text,markdown,html")
    assert page.headers and "content-type" in page.headers
    assert page.links and page.links[0]["url"].startswith("http")
    assert {r["kind"] for r in page.resources or []} >= {"image", "css", "js"}
    assert page.text and "<" not in page.text
    assert page.markdown and page.markdown.startswith("# ") and "![" in page.markdown
    assert page.html and page.html.startswith("<html")


def test_no_response_redirect_loop_and_errors_are_data(base_url: str) -> None:
    dead, loop, missing = fetch_many(["http://127.0.0.1:1/x", f"{base_url}/loop1", f"{base_url}/missing"])
    assert dead.status is None and dead.error and "Connect" in dead.error
    assert loop.error == "more than 10 redirects"
    assert missing.status == 404 and missing.error is None


def test_results_come_in_input_order(base_url: str) -> None:
    paths = ["/c", "/a", "/missing", "/b", "/old"]
    results = list(fetch_many([base_url + p for p in paths], CrawlSettings(concurrency=2)))
    assert [r.url.removeprefix(base_url) for r in results] == paths


def test_user_agent_and_headers_from_settings(base_url: str) -> None:
    page = fetch(f"{base_url}/g-blocked", CrawlSettings(user_agent="googlebot", headers={"Accept-Language": "ru"}))
    assert page.status == 200  # robots.txt is not consulted by fetch


def test_cli_json_lines_from_stdin_and_nothing_in_the_database(base_url: str) -> None:
    code, lines = _lines("--list", "-", "--include", "links", input=f"{base_url}/old\n# comment\n{base_url}/missing\n")
    assert code == 0 and [line["status"] for line in lines] == [200, 404]
    assert lines[0]["final_url"] == f"{base_url}/a" and lines[0]["links"]
    with storage.database() as engine, engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(storage.crawls)).scalar_one() == 0


def test_cli_markdown_documents(base_url: str) -> None:
    result = CliRunner().invoke(app, ["fetch", f"{base_url}/a", f"{base_url}/old", "--markdown"])
    assert result.exit_code == 0
    first, second = result.stdout.split("\n===\n")
    assert first.startswith("# Полигон spider: страница a") and "- Status: 200" in first and "---" in first
    assert "- Redirected from:" in second


def test_cli_human_and_bad_arguments(base_url: str) -> None:
    result = CliRunner().invoke(app, ["fetch", f"{base_url}/old"])
    assert result.exit_code == 0 and "200" in result.stdout and "/a" in result.stdout
    for args in ([], ["--include", "pdf", f"{base_url}/"], [f"{base_url}/", "--list", "x.txt"], ["not-a-url"]):
        result = CliRunner().invoke(app, ["--json", "fetch", *args])
        assert result.exit_code == 2, args


@pytest.mark.skipif(importlib.util.find_spec("playwright") is None, reason="the `render` extra is not installed")
def test_render_gives_the_js_page(base_url: str) -> None:
    page = fetch(f"{base_url}/js-only", render=True, include="markdown")
    assert page.rendered is True and page.seo and page.seo["title"] == "Заголовок из JS"
    assert page.markdown and "H1 из JS" in page.markdown


def test_to_markdown_of_a_failed_fetch() -> None:
    doc = FetchResult("https://nowhere.example/", error="ConnectError: no route").to_markdown()
    assert doc.startswith("# https://nowhere.example/") and "- Error: ConnectError" in doc


def test_html_to_markdown_keeps_structure_and_drops_chrome() -> None:
    html = b"""<body><nav><a href='/'>Menu</a></nav><main><h2>Title <em>x</em></h2>
    <p>Hi <b>bold</b>, <a href='/d?a=1'>docs</a>, <a href='#top'>top</a>.<br>two</p>
    <ul><li>One</li><li>Two<ol><li>Deep <code>c</code></li></ol></li></ul>
    <table><tr><th>N</th><th>P</th></tr><tr><td>a|b</td></tr></table><pre>x = 1\n  y</pre>
    <blockquote><p>Q</p></blockquote><hr><dl><dt>Term</dt><dd>Def</dd></dl><img src='/i.png' alt='Pic'>
    <aside>side</aside><script>s()</script></main><footer>foot</footer></body>"""
    md = html_to_markdown(html, "https://s.ex/p")
    assert md == (
        "## Title _x_\n\nHi **bold**, [docs](https://s.ex/d?a=1), top. two\n\n- One\n- Two\n  1. Deep `c`\n\n"
        "| N | P |\n|---|---|\n| a\\|b |  |\n\n```\nx = 1\n  y\n```\n\n> Q\n\n---\n\n**Term**\n\nDef\n\n"
        "![Pic](https://s.ex/i.png)\n"
    )
    assert html_to_markdown(b"<p>no body tag</p>", "https://s.ex/") == "no body tag\n"
