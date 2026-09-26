"""Security (#29): the HTTPS polygon (self-signed, crawl.verify_tls = false), HSTS, headers and sniffing."""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import issues, security, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.extract import missing_security_headers, sniffed_mismatch
from rb_spider.core.settings import CrawlSettings, Settings

from . import polygon


@pytest.fixture(scope="module")
def https_url():
    with polygon.serve(https=True) as url:
        yield url


def _crawl(engine, url: str, **crawl) -> int:
    return crawl_site(engine, f"{url}/", "secure", Settings(crawl=CrawlSettings(verify_tls=False, **crawl))).crawl_id


@pytest.fixture(scope="module")
def https_crawl(https_url: str):
    with storage.database() as engine:
        yield engine, _crawl(engine, https_url)


def _short(url: str, https_url: str) -> str:
    insecure = https_url.replace("https://", "http://")
    return url.removeprefix(https_url) if url.startswith(https_url) else url.replace(insecure, "INSECURE")


@pytest.mark.parametrize("code", sorted(polygon.HTTPS_EXPECTED))
def test_https_rules(code: str, https_url: str, https_crawl) -> None:
    engine, crawl_id = https_crawl
    _, rows = issues.urls_with(engine, crawl_id, code)
    assert {_short(row["url"], https_url) for row in rows} == polygon.HTTPS_EXPECTED[code]


def test_hsts_policy_turns_http_links_into_307(https_url: str, https_crawl) -> None:
    engine, crawl_id = https_crawl
    insecure = https_url.replace("https://", "http://")
    with engine.connect() as conn:
        row = (
            conn.execute(
                sa.select(storage.pages).where(
                    storage.pages.c.crawl_id == crawl_id, storage.pages.c.url == f"{insecure}/plain"
                )
            )
            .mappings()
            .one()
        )
    assert (row["status_code"], row["redirect_url"]) == (307, f"{https_url}/plain")
    assert row["error"].startswith("HSTS Policy")


def test_without_respect_hsts_http_links_are_fetched(https_url: str) -> None:
    insecure = https_url.replace("https://", "http://")
    with storage.database() as engine:
        crawl_id = _crawl(engine, https_url, respect_hsts=False)
        with engine.connect() as conn:
            status = conn.execute(
                sa.select(storage.pages.c.status_code).where(
                    storage.pages.c.crawl_id == crawl_id, storage.pages.c.url == f"{insecure}/plain"
                )
            ).scalar_one()
    assert status == 0  # plain HTTP to a TLS port: no response — the real answer, not the browser's 307


def test_self_signed_certificate_is_refused_by_default(https_url: str) -> None:
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{https_url}/", "secure").crawl_id
        _, rows = issues.urls_with(engine, crawl_id, "internal_no_response")
    assert [row["url"] for row in rows] == [f"{https_url}/"]


def test_insecure_content_report_and_scheme_counts(https_url: str, https_crawl) -> None:
    engine, crawl_id = https_crawl
    total, rows = security.insecure_content(engine, crawl_id)
    assert {(_short(r["source"], https_url), r["kind"], _short(r["target"], https_url)) for r in rows} == {
        ("/", "hyperlink", "INSECURE/plain"),
        ("/mixed", "image", "INSECURE/img.png"),
        ("/form-insecure", "form", "INSECURE/submit"),
    }
    assert total == 3
    with engine.connect() as conn:
        counts = security.counts(conn, crawl_id)
    assert counts["http"] == 2 and counts["https"] > 2


def test_cli_insecure_and_export_scheme(https_url: str) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["--json", "crawl", f"{https_url}/", "--set", "crawl.verify_tls=false"]).exit_code == 0
    result = runner.invoke(app, ["--json", "insecure", "--limit", "1"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert (data["total"], len(data["links"])) == (3, 1)
    exported = runner.invoke(app, ["export", "pages", "--scheme", "http", "--format", "json"])
    assert exported.exit_code == 0
    assert {row["url"].rsplit("/", 1)[1] for row in json.loads(exported.stdout)} == {"plain", "img.png"}
    assert runner.invoke(app, ["--json", "export", "links", "--scheme", "http"]).exit_code == 2


@pytest.mark.parametrize(
    ("headers", "missing"),
    [
        ({}, ",hsts,csp,xcto,xfo,referrer,"),
        ({"strict-transport-security": "max-age=1", "content-security-policy": "default-src 'self'",
          "x-content-type-options": "NoSniff", "x-frame-options": "deny",
          "referrer-policy": "unsafe-url, strict-origin"}, None),  # the last known policy counts
        ({"referrer-policy": "strict-origin, unsafe-url", "x-frame-options": "ALLOWALL"}, ",hsts,csp,xcto,xfo,referrer,"),
    ],
)  # fmt: skip
def test_missing_security_headers(headers: dict, missing: str | None) -> None:
    assert missing_security_headers(headers) == missing


@pytest.mark.parametrize(
    ("content_type", "body", "found"),
    [
        ("image/png", b"<!DOCTYPE html><html>", "image → html"),
        ("text/html; charset=utf-8", b"\x89PNG\r\n\x1a\nxxxx", "html → image"),
        ("text/html", b"\xef\xbb\xbf  <!-- c --> <html lang=ru>", None),
        ("application/json", b'{"a": 1}', None),
        ("image/webp", b"RIFF\0\0\0\0WEBPVP8 ", None),
        ("text/plain", b"%PDF-1.7", "other → pdf"),
        (None, b"<html>", None),
    ],
)
def test_sniffed_mismatch(content_type: str | None, body: bytes, found: str | None) -> None:
    assert sniffed_mismatch(content_type, body) == found
