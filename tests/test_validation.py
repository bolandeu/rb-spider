"""HTML validation and mobile (#34): the source-level checks, plugins, viewport and the mobile alternate."""

from __future__ import annotations

import pytest

from rb_spider.core import issues, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.extract import parse_page, validation
from rb_spider.core.settings import CollectSettings, FollowStore, Settings

from . import polygon


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (b"<!DOCTYPE html><html lang=ru><head><title>t</title></head><body></body></html>",
         (1, 1, False, False, None)),
        (b"<p>x</p><html><head><title>t</title><img src=a><meta name=x></head><body></body></html>",
         (1, 1, True, False, "img")),
        (b"<html><body><head></head></body><body></body></html>", (1, 2, False, True, None)),
        # scripts, comments and noscript are raw text: their markup is not elements of <head>
        (b'<html><head><script>var a="<div>"</script><!-- <p> --><noscript><img src=x></noscript></head><body>',
         (1, 1, False, False, None)),
        (b"<html><header></header><bodyguard></bodyguard></html>", (0, 0, False, False, None)),  # not head / body
    ],
)  # fmt: skip
def test_validation_reads_the_source(source: bytes, expected: tuple) -> None:
    found = validation(source)
    names = ("head_tags", "body_tags", "body_before_html", "head_not_first", "invalid_head_element")
    assert tuple(found[n] for n in names) == expected


def test_mobile_extraction() -> None:
    body = (b'<html><head><meta name="Viewport" content="width=device-width">'
            b'<link rel="alternate" media="only screen and (max-width: 640px)" href="https://m.s.example/">'
            b'<link rel="alternate" hreflang="en" media="all" href="/en"></head><body>'
            b'<embed src="/a.swf"><object data="/b.xap" type="application/x-silverlight-2"></object>'
            b'<object data="/c.pdf" type="application/pdf"></object><applet code="A.class"></applet></body></html>')  # fmt: skip
    page = parse_page("https://s.example/", 200, {"Content-Type": "text/html"}, body)
    assert page.onpage["viewport"] == "width=device-width"
    assert page.onpage["plugins"] == 3  # the PDF object is not a plugin
    assert page.mobile_alternates == ["https://m.s.example/"]  # the hreflang alternate is not a mobile one


def test_switches_turn_the_checks_off(base_url: str) -> None:
    collect = CollectSettings(html_validation=False, mobile_alternate=FollowStore(follow=False, store=False))
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/", "polygon", Settings(collect=collect)).crawl_id
        unchecked = {r.code for r in issues.not_checked(engine, crawl_id)}
        _, rows = issues.urls_with(engine, crawl_id, "validation_document_over_max")
        with engine.connect() as conn:
            mobile_page = conn.execute(
                storage.pages.select().where(
                    storage.pages.c.crawl_id == crawl_id, storage.pages.c.url == f"{base_url}/m/page"
                )
            ).first()
    assert {"validation_missing_head", "validation_head_not_first", "mobile_alternate_link"} <= unchecked
    assert "validation_document_over_max" not in unchecked and len(rows) == 1  # size needs no source scan
    assert mobile_page is None  # the mobile alternate wasn't followed
