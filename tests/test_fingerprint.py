"""crawl.fingerprint: one browser identity for a whole crawl — the same headers on every request, and in the
browser what a site's script reads (navigator, screen, WebGL, time zone, WebRTC off)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import fingerprint, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.errors import InvalidArguments
from rb_spider.core.settings import CrawlSettings, Settings
from rb_spider.fetch import fetch

from . import polygon

# a fingerprint service's file (format 2.0), as users download it; the IP is a documentation one
WINDOWS: dict[str, Any] = {
    "ip": "203.0.113.22",
    "geo": {"country_iso": "RU", "timezone": "Europe/Moscow", "locale": "ru-RU"},
    "os": "windows",
    "browser": "chrome",
    "browser_version": "155.0.0.0",
    "navigator": {
        "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/155.0.0.0 Safari/537.36",
        "platform": "Win32",
        "language": "ru-RU",
        "languages": ["ru-RU", "ru", "en-US", "en"],
        "accept_language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "hardwareConcurrency": 12,
        "deviceMemory": 8,
        "maxTouchPoints": 0,
        "doNotTrack": None,
        "userAgentData": {"mobile": False, "platform": "Windows"},
    },
    "screen": {"width": 1920, "height": 1080, "availWidth": 1920, "availHeight": 1043, "colorDepth": 24,
               "pixelDepth": 24, "pixelRatio": 1},
    "webgl": {"vendor": "Google Inc. (NVIDIA)",
              "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    "canvas": {"noiseSeed": 455606},
    "fonts": ["Arial", "Calibri", "Segoe UI"],
    "timezone": {"name": "Europe/Moscow", "offset": -180},
    "_meta": {"version": "2.0", "engine": "chromium", "tcp_match": "windows_11"},
}  # fmt: skip

ANDROID: dict[str, Any] = {
    **WINDOWS,
    "os": "android",
    "navigator": {
        **WINDOWS["navigator"],
        "userAgent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/155.0.0.0 Mobile Safari/537.36",
        "platform": "Linux armv81",
        "maxTouchPoints": 5,
        "userAgentData": {"mobile": True, "platform": "Android", "platformVersion": "15.0.0", "model": "SM-S911B"},
    },
    "screen": {"width": 360, "height": 780, "availWidth": 360, "availHeight": 780, "pixelRatio": 3},
    "webgl": {"vendor": "Qualcomm", "renderer": "Adreno (TM) 740"},
    "fonts": ["Roboto", "Noto Sans", "Droid Sans Mono"],
    "_meta": {"version": "2.0", "tcp_match": "android_15"},
}

needs_browser = pytest.mark.skipif(importlib.util.find_spec("playwright") is None, reason="extra rb-spider[render]")


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture(autouse=True)
def geo(base_url: str, monkeypatch) -> None:
    """The exit IP's place comes from the polygon, not from ipinfo.io."""
    monkeypatch.setattr(fingerprint, "GEO_URL", f"{base_url}/geo")
    monkeypatch.setitem(polygon.GEO, "timezone", "Europe/Moscow")


def _add(tmp_path: Path, data: dict, name: str) -> str:
    source = tmp_path / f"{name}.json"
    source.write_text(json.dumps(data))
    result = CliRunner().invoke(app, ["--json", "fingerprints", "add", str(source), "--name", name])
    assert result.exit_code == 0, result.output
    return name


@pytest.fixture
def windows(tmp_path: Path) -> str:
    source = tmp_path / "fp.json"
    source.write_text(json.dumps(WINDOWS))
    result = CliRunner().invoke(app, ["--json", "fingerprints", "add", str(source), "--name", "win"])
    assert result.exit_code == 0, result.output
    return "win"


def test_chrome_brands_are_greased_like_chrome() -> None:
    # Chrome 147 as browserforge recorded it from real browsers
    assert fingerprint.chrome_brands(147) == [{"brand": "Google Chrome", "version": "147"},
                                              {"brand": "Not.A/Brand", "version": "8"},
                                              {"brand": "Chromium", "version": "147"}]  # fmt: skip


def test_every_request_carries_the_fingerprints_headers(base_url: str, windows: str) -> None:
    polygon.SEEN_HEADERS.clear()
    with storage.database() as engine:
        crawl_site(engine, f"{base_url}/a", "polygon", Settings(crawl=CrawlSettings(fingerprint=windows, max_urls=3)))
    sent = [h for h in polygon.SEEN_HEADERS if "sec-ch-ua" in h]
    assert sent and all(h["user-agent"] == WINDOWS["navigator"]["userAgent"] for h in sent)
    assert sent[0]["accept-language"] == "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    assert sent[0]["sec-ch-ua"] == '"Google Chrome";v="155", "Chromium";v="155", "Not(A:Brand";v="24"'
    assert sent[0]["sec-ch-ua-platform"] == '"Windows"'


def test_an_explicit_user_agent_wins(windows: str) -> None:
    settings, _ = fingerprint.apply(CrawlSettings(fingerprint=windows, user_agent="googlebot",
                                                  headers={"Accept-Language": "en"}))  # fmt: skip
    assert settings.user_agent == "googlebot" and settings.headers["Accept-Language"] == "en"


@needs_browser
def test_the_browser_shows_the_fingerprint(base_url: str, windows: str) -> None:
    settings = CrawlSettings(fingerprint=windows, render_wait_ms=500)  # the page waits 300 ms for WebRTC
    page = fetch(f"{base_url}/js/fingerprint", settings, render=True, include="text")
    assert page.rendered and page.text
    seen = json.loads(page.text.split("FP")[1])
    assert seen["ua"] == WINDOWS["navigator"]["userAgent"] and seen["platform"] == "Win32"
    assert (seen["cores"], seen["memory"], seen["languages"]) == (12, 8, ["ru-RU", "ru", "en-US", "en"])
    assert seen["screen"] == "1920x1080" and seen["tz"] == "Europe/Moscow"
    assert seen["brands"] == ["Google Chrome", "Chromium", "Not(A:Brand"]
    assert "RTX 3060" in (seen["webgl"] or "") and seen["webdriver"] is False
    assert seen["rtc"] == "function" and seen["ips"] == []  # WebRTC works, but shows no local or real IP


def test_a_missing_or_broken_file_is_refused_before_the_crawl(tmp_path: Path) -> None:
    with pytest.raises(InvalidArguments, match="no file"):
        fingerprint.apply(CrawlSettings(fingerprint="nope"))
    broken = tmp_path / "broken.json"
    broken.write_text('{"navigator": {}}')
    code = CliRunner().invoke(app, ["--json", "fingerprints", "add", str(broken)]).exit_code
    assert code == 2


def test_list_show_and_replace(tmp_path: Path, windows: str) -> None:
    listing = json.loads(CliRunner().invoke(app, ["--json", "fingerprints", "list"]).stdout)
    assert [f["name"] for f in listing["fingerprints"]] == ["win"]
    shown = json.loads(CliRunner().invoke(app, ["--json", "fingerprints", "show", "win"]).stdout)
    assert shown["headers"]["sec-ch-ua-platform"] == '"Windows"' and "canvas" in shown["not_faked"]
    again = tmp_path / "fp.json"
    assert CliRunner().invoke(app, ["--json", "fingerprints", "add", str(again), "--name", "win"]).exit_code == 2
    assert (
        CliRunner().invoke(app, ["--json", "fingerprints", "add", str(again), "--name", "win", "--force"]).exit_code
        == 0
    )


@needs_browser
def test_new_generates_a_current_chrome(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["--json", "fingerprints", "new", "gen", "--os", "windows", "--chrome", "155"])
    assert result.exit_code == 0, result.output
    found = fingerprint.load("gen")
    assert "Chrome/155.0.0.0" in found.navigator.userAgent and found.navigator.languages[:2] == ["ru-RU", "ru"]
    assert found.headers()["sec-ch-ua"].count('v="155"') == 2


@pytest.mark.parametrize("data", [WINDOWS, ANDROID], ids=["windows", "android"])
def test_a_service_fingerprint_is_consistent(data: dict) -> None:
    assert fingerprint.os_issues(fingerprint.FingerprintFile.model_validate(data)) == []


def test_contradictions_are_named() -> None:
    mixed = {**WINDOWS, "webgl": {"renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M3)"},
             "fonts": ["Segoe UI", "Menlo"], "_meta": {"tcp_match": "android_15"}}  # fmt: skip
    issues = " | ".join(fingerprint.os_issues(fingerprint.FingerprintFile.model_validate(mixed)))
    assert "GPU" in issues and "Menlo" in issues and "TCP" in issues


def test_check_compares_with_the_exit_ip(tmp_path: Path, windows: str, monkeypatch) -> None:
    result = CliRunner().invoke(app, ["--json", "fingerprints", "check", windows])
    data = json.loads(result.stdout)
    assert result.exit_code == 0 and data["ok"] and data["exit_ip"]["country"] == "RU"
    monkeypatch.setitem(polygon.GEO, "timezone", "Asia/Novosibirsk")
    data = json.loads(CliRunner().invoke(app, ["--json", "fingerprints", "check", windows]).stdout)
    assert data["ok"]  # crawl.fingerprint_timezone = ip: the browser takes the IP's time zone anyway
    keep = ["--set", "crawl.fingerprint_timezone=file"]
    data = json.loads(CliRunner().invoke(app, ["--json", "fingerprints", "check", windows, *keep]).stdout)
    assert not data["ok"] and "Asia/Novosibirsk" in data["issues"][0]


def test_a_crawl_stops_on_a_mismatch_when_asked(base_url: str, windows: str, monkeypatch) -> None:
    from rb_spider.core.crawl import register_crawl, run_crawl
    from rb_spider.core.errors import FingerprintMismatch

    monkeypatch.setitem(polygon.GEO, "timezone", "Asia/Novosibirsk")
    crawl = CrawlSettings(fingerprint=windows, fingerprint_check="stop", fingerprint_timezone="file", max_urls=2)
    with storage.database() as engine:
        crawl_id = register_crawl(engine, f"{base_url}/a", "polygon", Settings(crawl=crawl))
        with pytest.raises(FingerprintMismatch, match="Novosibirsk"):
            run_crawl(engine, crawl_id)
        warned = crawl_site(engine, f"{base_url}/a", "polygon",
                            Settings(crawl=crawl.model_copy(update={"fingerprint_check": "warn"})))  # fmt: skip
    assert warned.status == "finished"


@needs_browser
def test_an_android_fingerprint_is_a_phone_in_the_browser(base_url: str, tmp_path: Path) -> None:
    name = _add(tmp_path, ANDROID, "phone")
    settings = CrawlSettings(fingerprint=name, render_wait_ms=500)
    page = fetch(f"{base_url}/js/fingerprint", settings, render=True, include="text")
    seen = json.loads((page.text or "").split("FP")[1])
    assert seen["platform"] == "Linux armv81" and seen["screen"] == "360x780" and "Adreno" in (seen["webgl"] or "")


@needs_browser
def test_the_browsers_time_zone_is_the_exit_ips(base_url: str, windows: str, monkeypatch) -> None:
    monkeypatch.setitem(polygon.GEO, "timezone", "Asia/Novosibirsk")  # a mobile IP far from the file's Moscow
    settings = CrawlSettings(fingerprint=windows, render_wait_ms=500)
    page = fetch(f"{base_url}/js/fingerprint", settings, render=True, include="text")
    assert json.loads((page.text or "").split("FP")[1])["tz"] == "Asia/Novosibirsk"
    kept = fetch(f"{base_url}/js/fingerprint", settings.model_copy(update={"fingerprint_timezone": "file",
                 "fingerprint_check": "off"}), render=True, include="text")  # fmt: skip
    assert json.loads((kept.text or "").split("FP")[1])["tz"] == "Europe/Moscow"
