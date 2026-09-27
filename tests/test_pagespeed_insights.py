"""`spider lighthouse --source psi` (#42): the same audits from PageSpeed Insights, plus CrUX — through the gsc
package's fake client (no network, no key): the polygon's /lh/ pages fail the audit they are named after."""

from __future__ import annotations

import json
import sys

import pytest
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import issues, lighthouse, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.settings import CrawlSettings, Settings

from . import polygon
from .conftest import use_db

gsc = pytest.importorskip("gsc")
from gsc.testing import FakePageSpeed  # noqa: E402 — after the skip: gsc is an extra

REAL_CLIENT = lighthouse.pagespeed_client


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture
def crawled(base_url: str, monkeypatch):
    with storage.database() as engine:
        crawl_id = crawl_site(engine, f"{base_url}/lh/", "polygon", Settings(crawl=CrawlSettings(max_depth=1))).crawl_id
        use_db(monkeypatch, engine)
        yield engine, crawl_id


def _result(url: str, strategy: str = "desktop") -> gsc.PageSpeedResult:
    """What PSI answers for a polygon page: the audit the page is named after fails, the rest pass."""
    last = url.rstrip("/").rsplit("/", 1)[-1]
    audits = [
        gsc.Audit(id=audit_id, score=0.0 if last == audit_id else 1.0,
                  display_value=f"{audit_id} on {last}" if last == audit_id else None,
                  details=[{"url": url + "/app.js", "wastedBytes": 1000}] if last == audit_id else [])
        for audit_id in polygon._lh_audits()
    ]  # fmt: skip
    audits.append(gsc.Audit(id="largest-contentful-paint", score=0.8, numeric_value=2500.0, display_value="2.5 s"))
    metric = gsc.CruxMetric(percentile=4100, value=4100, category="SLOW", good=0.4, needs_improvement=0.3, poor=0.3)
    return gsc.PageSpeedResult(
        url=url, final_url=url, strategy=strategy, scores={"performance": 0.5, "accessibility": 0.9}, audits=audits,
        crux_url=gsc.Crux(id=url, overall_category="SLOW", lcp=metric) if last == "lh" else None,
        crux_origin=gsc.Crux(id="origin", overall_category="AVERAGE",
                             cls=gsc.CruxMetric(percentile=12, value=0.12, category="AVERAGE")),
    )  # fmt: skip


@pytest.fixture
def psi(base_url: str, monkeypatch) -> FakePageSpeed:
    fake = FakePageSpeed({f"{base_url}{path}": _result(f"{base_url}{path}") for path in polygon.LH_PAGES})
    monkeypatch.setattr(lighthouse, "pagespeed_client", lambda: fake)
    return fake


def _run(*args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(app, ["--json", "lighthouse", "--source", "psi", "--strategy", "desktop", *args])
    return result.exit_code, json.loads(result.stdout)


def test_every_pagespeed_rule_finds_its_page(crawled, psi: FakePageSpeed, base_url: str) -> None:
    engine, crawl_id = crawled
    code, data = _run("--all")
    assert code == 0 and data["source"] == "psi" and all(p["ok"] for p in data["pages"]) and data["findings"] > 0
    assert {c[1:] for c in psi.calls} == {("desktop", ("performance", "accessibility"))}
    for code_, paths in polygon.LH_EXPECTED.items():
        if code_.startswith("pagespeed_"):
            _, rows = issues.urls_with(engine, crawl_id, code_)
            assert {r["url"].removeprefix(base_url) for r in rows} == paths, code_
    page = next(p for p in data["pages"] if p["url"].endswith("/lh/unminified-css"))
    assert page["performance"] == 0.5 and page["metrics"]["lcp_ms"] == 2500 and page["failed"] == ["unminified-css"]


def test_crux_in_url_details_and_export(crawled, psi: FakePageSpeed, base_url: str) -> None:
    assert _run(f"{base_url}/lh/", f"{base_url}/lh/unused-javascript")[0] == 0
    runner = CliRunner()
    details = json.loads(runner.invoke(app, ["--json", "url", f"{base_url}/lh/"]).stdout)["lighthouse"]["desktop"]
    assert details["source"] == "psi" and details["categories"]["performance"] == 0.5
    assert details["crux"]["url"]["lcp"] == {"value": 4100, "category": "SLOW"}
    assert details["crux"]["url"]["overall"]["category"] == "SLOW"
    assert details["crux"]["origin"]["cls"] == {"value": 0.12, "category": "AVERAGE"}
    other = json.loads(runner.invoke(app, ["--json", "url", f"{base_url}/lh/unused-javascript"]).stdout)
    assert "url" not in other["lighthouse"]["desktop"]["crux"]  # Google has no field data for this page
    human = runner.invoke(app, ["url", f"{base_url}/lh/"]).stdout
    assert "PageSpeed Insights" in human and "CrUX, страница: SLOW" in human
    exported = runner.invoke(app, ["export", "lighthouse"]).stdout
    assert exported.splitlines()[0].endswith(",source") and "crux:lcp" in exported and ",psi" in exported


def test_a_failed_page_is_reported_not_fatal(crawled, psi: FakePageSpeed, base_url: str) -> None:
    psi.results[f"{base_url}/lh/"] = gsc.ApiError("pagespeed", "Lighthouse returned error: NO_FCP", status=500)
    code, data = _run(f"{base_url}/lh/", f"{base_url}/lh/unused-javascript")
    assert code == 0 and [p["ok"] for p in data["pages"]] == [False, True] and "NO_FCP" in data["pages"][0]["error"]


def test_no_key_quota_and_no_gsc(crawled, psi: FakePageSpeed, base_url: str, monkeypatch) -> None:
    engine, _ = crawled
    first, second = f"{base_url}/lh/unused-javascript", f"{base_url}/lh/"
    psi.results[first] = gsc.NotAuthorized("pagespeed", "нет ключа", action="gsc auth login --provider pagespeed")
    code, data = _run(first)
    assert code == 3 and data["error"]["code"] == "AUTH_REQUIRED" and "gsc auth login" in data["error"]["action"]
    psi.results[first] = _result(first)
    psi.results[second] = gsc.QuotaExceeded("pagespeed", "дневная квота", retry_after=3600, daily=True)
    code, data = _run(first, second)
    assert code == 5 and data["error"]["code"] == "PROVIDER_ERROR"
    with engine.connect() as conn:
        stored = conn.execute(storage.lighthouse_audits.select().where(storage.lighthouse_audits.c.url == first)).all()
    assert stored and {r.source for r in stored} == {"psi"}  # measured before the quota: kept
    monkeypatch.setattr(lighthouse, "pagespeed_client", REAL_CLIENT)  # and no gsc to import
    monkeypatch.setitem(sys.modules, "gsc", None)
    code, data = _run(first)
    assert code == 1 and data["error"]["code"] == "PAGESPEED_UNAVAILABLE"


def test_doctor_reports_the_pagespeed_key(monkeypatch) -> None:
    from rb_spider.commands import doctor

    monkeypatch.setattr(gsc, "auth_status", lambda: gsc.AuthStatus(google="missing", pagespeed_key=False))
    found = doctor._pagespeed_check()
    assert found["ok"] and "gsc auth login --provider pagespeed" in found["detail"]
    monkeypatch.setitem(sys.modules, "gsc", None)
    assert "не установлен" in doctor._pagespeed_check()["detail"]
