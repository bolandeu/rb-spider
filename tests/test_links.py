from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import issues, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.settings import CollectSettings, FollowStore, Settings

from . import polygon


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


def _invoke_json(*args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(app, ["--json", *args])
    return result.exit_code, json.loads(result.stdout)


def test_links_out_and_in(base_url: str) -> None:
    assert _invoke_json("crawl", f"{base_url}/")[0] == 0

    code, out = _invoke_json("links", f"{base_url}/l-nofollow", "--out")
    assert code == 0
    by_target = {link["target"].removeprefix(base_url): link for link in out["links"]}
    assert by_target["/l-nofollow-only"]["nofollow"] is True
    assert by_target["/l-nofollow-only"]["status_code"] is None  # nofollow: not crawled
    assert by_target["/"]["status_code"] == 200
    assert by_target["/"]["kind"] == "hyperlink"

    code, inbound = _invoke_json("links", f"{base_url}/missing", "--in")
    assert code == 0
    sources = {link["source"].removeprefix(base_url): link for link in inbound["links"]}
    assert set(sources) == {"/", "/to-missing"}  # "who links to this 404" includes redirects to it
    assert (sources["/"]["kind"], sources["/"]["status_code"]) == ("hyperlink", 200)
    assert (sources["/to-missing"]["kind"], sources["/to-missing"]["status_code"]) == ("redirect", 301)

    code, canon = _invoke_json("links", f"{base_url}/c-unlinked", "--in")
    assert [link["kind"] for link in canon["links"]] == ["canonical"]

    code, _ = _invoke_json("links", f"{base_url}/", "--in", "--out")
    assert code == 2


def test_not_storing_links_marks_link_checks_not_checked(base_url: str) -> None:
    collect = CollectSettings(internal_links=FollowStore(follow=True, store=False))
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/", "polygon", Settings(collect=collect)).crawl_id
        skipped = {r.code for r in issues.not_checked(engine, crawl_id)}
        found = {s.code for s in issues.summary(engine, crawl_id)}
        assert storage.links_of(engine, crawl_id, f"{base_url}/")[0] > 0  # external links are still kept
    assert {"links_nofollow_inlinks_only", "links_no_anchor_text", "canonical_unlinked"} <= skipped
    assert not skipped & found
    assert "links_internal_nofollow_outlinks" in found  # page counters don't need stored links

    _, summary = _invoke_json("issues", str(crawl_id))
    assert "links_nofollow_inlinks_only" in {r["code"] for r in summary["not_checked"]}


def test_not_following_external_links(base_url: str) -> None:
    collect = CollectSettings(external_links=FollowStore(follow=False, store=True))
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/", "polygon", Settings(collect=collect)).crawl_id
        with engine.connect() as conn:
            externals = conn.execute(
                storage.pages.select().where(storage.pages.c.crawl_id == crawl_id, storage.pages.c.external)
            ).fetchall()
        skipped = {r.code for r in issues.not_checked(engine, crawl_id)}
    # no other site's link was checked; the external <img> still is — collect.images decides that
    assert [row.url.rsplit("/", 2)[-2:] for row in externals] == [["img", "gone.png"]]
    assert {"external_no_response", "external_client_error", "external_server_error"} <= skipped


def test_collect_images_follow_and_store(base_url: str) -> None:
    with storage.database() as engine:
        off = CollectSettings(images=FollowStore(follow=False, store=False))
        crawl_id = crawl_site(engine, f"{base_url}/", "polygon", Settings(collect=off)).crawl_id
        with engine.connect() as conn:
            fetched = {row.url.removeprefix(base_url) for row in conn.execute(
                storage.pages.select().where(storage.pages.c.crawl_id == crawl_id))}  # fmt: skip
        skipped = {r.code for r in issues.not_checked(engine, crawl_id)}
    assert "/img/big.png" not in fetched and "/style.css" in fetched  # images off, CSS still checked
    assert {"images_missing_alt_attribute", "images_over_max_kb", "internal_blocked_resource"} <= skipped
