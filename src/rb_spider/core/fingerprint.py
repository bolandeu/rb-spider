"""A browser fingerprint from a file (`crawl.fingerprint`): the identity that goes with a proxy.

The file is JSON of a fingerprint service (format 2.0: `navigator`, `screen`, `webgl`, `timezone`, `fonts`…),
kept in the user's fingerprints folder (next to the global config: `~/.config/spider/fingerprints/` on Linux,
`~/Library/Application Support/spider/fingerprints/` on macOS) and named by `crawl.fingerprint` — or a path.

Where it goes:
- every request (`apply`): User-Agent, Accept-Language and Chrome's client hints (`sec-ch-ua*`), unless
  crawl.user_agent / crawl.headers set them;
- the browser (`browserforge`): navigator (platform, languages, cores, memory, userAgentData), screen, WebGL,
  codecs — injected by browserforge's script, the
  way Crawlee injects its own generated fingerprints — plus the time zone and locale of the context.
Canvas noise, the audio hash and fonts are not faked: browserforge has no injection for them.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import settings as settings_module
from .errors import FingerprintMismatch, InvalidArguments
from .settings import CrawlSettings

log = logging.getLogger(__name__)


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class Navigator(_Loose):
    userAgent: str
    platform: str = "MacIntel"
    language: str = "en-US"
    languages: list[str] = Field(default_factory=lambda: ["en-US", "en"])
    accept_language: str | None = None
    hardwareConcurrency: int = 8
    deviceMemory: int | None = 8
    maxTouchPoints: int = 0
    doNotTrack: str | None = None
    userAgentData: dict[str, Any] = Field(default_factory=dict)


class Screen(_Loose):
    width: int = 1920
    height: int = 1080
    availWidth: int | None = None
    availHeight: int | None = None
    colorDepth: int = 24
    pixelDepth: int = 24
    pixelRatio: float = 1


class WebGl(_Loose):
    vendor: str = "Google Inc."
    renderer: str = ""


class TimeZone(_Loose):
    name: str | None = None


class Geo(_Loose):
    country_iso: str | None = None
    timezone: str | None = None
    locale: str | None = None


class FingerprintFile(_Loose):
    """What spider reads of a fingerprint file; other fields are kept and ignored."""

    ip: str | None = None
    os: str | None = None
    browser: str = "chrome"
    browser_version: str | None = None
    navigator: Navigator
    screen: Screen = Field(default_factory=Screen)
    webgl: WebGl = Field(default_factory=WebGl)
    timezone: TimeZone = Field(default_factory=TimeZone)
    geo: Geo = Field(default_factory=Geo)
    fonts: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict, alias="_meta")

    @property
    def major(self) -> str:
        version = self.browser_version or self.navigator.userAgent.split("Chrome/")[-1]
        return version.split(".")[0] if version[:1].isdigit() else "0"

    @property
    def accept_language(self) -> str:
        if self.navigator.accept_language:
            return self.navigator.accept_language
        parts = [
            lang if i == 0 else f"{lang};q={max(0.1, 1 - i / 10):.1f}"
            for i, lang in enumerate(self.navigator.languages)
        ]
        return ",".join(parts)

    @property
    def platform_name(self) -> str:
        """The client-hints platform: macOS, Windows, Linux, Android."""
        return str(self.navigator.userAgentData.get("platform") or {"macos": "macOS", "windows": "Windows",
                   "linux": "Linux", "android": "Android"}.get((self.os or "").lower(), "Windows"))  # fmt: skip

    @property
    def platform_version(self) -> str:
        """The client-hints OS version, from the TCP fingerprint the service matched (`_meta.tcp_match`)."""
        match = str(self.meta.get("tcp_match", ""))
        return {"windows_10": "10.0.0", "windows_11": "15.0.0"}.get(match, "15.0.0" if "macos" in match else "10.0.0")

    @property
    def mobile(self) -> bool:
        return bool(self.navigator.userAgentData.get("mobile", False))

    @property
    def time_zone(self) -> str | None:
        return self.timezone.name or self.geo.timezone

    @property
    def locale(self) -> str:
        return self.geo.locale or self.navigator.language

    def brands(self) -> list[dict[str, str]]:
        return chrome_brands(int(self.major))

    def headers(self) -> dict[str, str]:
        """The browser-wide request headers this fingerprint sends."""
        found = {"User-Agent": self.navigator.userAgent, "Accept-Language": self.accept_language}
        if self.browser.lower() in ("chrome", "chromium", "edge"):
            found["sec-ch-ua"] = ", ".join(f'"{b["brand"]}";v="{b["version"]}"' for b in self.brands())
            found["sec-ch-ua-mobile"] = "?1" if self.mobile else "?0"
            found["sec-ch-ua-platform"] = f'"{self.platform_name}"'
        return found


_GREASE_CHARS = (" ", "(", ":", "-", ".", "/", ")", ";", "=", "?", "_")
_GREASE_VERSIONS = ("8", "99", "24")
_ORDERS = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))


def chrome_brands(major: int) -> list[dict[str, str]]:
    """navigator.userAgentData.brands / sec-ch-ua of Chrome `major`, as Chrome makes them: the fake "GREASE" brand
    and the order are picked by the major version (Chromium's GetGreasedUserAgentBrandVersion)."""
    grease = {"brand": f"Not{_GREASE_CHARS[major % 11]}A{_GREASE_CHARS[(major + 1) % 11]}Brand",
              "version": _GREASE_VERSIONS[major % 3]}  # fmt: skip
    listed = [grease, {"brand": "Chromium", "version": str(major)}, {"brand": "Google Chrome", "version": str(major)}]
    found: list[dict[str, str]] = [{}, {}, {}]
    for item, position in zip(listed, _ORDERS[major % 6], strict=True):
        found[position] = item
    return found


def fingerprints_dir() -> Path:
    """The user's fingerprint files, for every project: next to the global config."""
    return settings_module.global_config_path().parent / "fingerprints"  # via the module: tests move it


def fingerprint_path(name: str) -> Path:
    looks_like_path = "/" in name or "\\" in name or name.endswith(".json")
    return Path(name).expanduser() if looks_like_path else fingerprints_dir() / f"{name}.json"


def available() -> dict[str, Path]:
    folder = fingerprints_dir()
    return {p.stem: p for p in sorted(folder.glob("*.json"))} if folder.is_dir() else {}


def load(name: str) -> FingerprintFile:
    """`crawl.fingerprint`: a name in the fingerprints folder or a path to a JSON file."""
    path = fingerprint_path(name)
    if not path.is_file():
        known = ", ".join(available()) or "none yet"
        raise InvalidArguments(
            f"crawl.fingerprint: no file '{path}'. Put the JSON into {fingerprints_dir()} "
            f"(`spider fingerprints add FILE --name NAME`); there: {known}."
        )
    try:
        return FingerprintFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, ValidationError) as exc:
        raise InvalidArguments(f"crawl.fingerprint: '{path}' is not a fingerprint file ({str(exc)[:300]}).") from exc


def apply(settings: CrawlSettings) -> tuple[CrawlSettings, FingerprintFile | None]:
    """The settings with the fingerprint's headers, and the fingerprint (for the browser); an explicit
    crawl.user_agent or header wins."""
    if not settings.fingerprint:
        return settings, None
    found = load(settings.fingerprint)
    headers = {k: v for k, v in found.headers().items() if k != "User-Agent"}
    present = {k.lower() for k in settings.headers}
    update: dict[str, Any] = {"headers": {**{k: v for k, v in headers.items() if k.lower() not in present},
                                          **settings.headers}}  # fmt: skip
    if settings.user_agent is None:
        update["user_agent"] = found.navigator.userAgent
    return settings.model_copy(update=update), found


def context_options(found: FingerprintFile) -> dict[str, Any]:
    """Browser context options the injected script can't set: the time zone, locale and — a phone — touch."""
    found_options = {k: v for k, v in (("timezone_id", found.time_zone), ("locale", found.locale)) if v}
    return found_options | ({"is_mobile": True, "has_touch": True} if found.mobile else {})


def browserforge(found: FingerprintFile) -> Any:
    """The fingerprint as browserforge's, for Crawlee's browser plugin to inject (the `render` extra)."""
    from browserforge.fingerprints import Fingerprint, NavigatorFingerprint, ScreenFingerprint, VideoCard

    screen, nav = found.screen, found.navigator
    avail_w, avail_h = screen.availWidth or screen.width, screen.availHeight or screen.height
    inner_h = max(avail_h - (110 if found.mobile else 85), 100)  # the address bar (and a desktop window's toolbars)
    arm = "Apple M" in found.webgl.renderer or "arm" in nav.platform.lower()
    ua_data: dict[str, Any] = {
        "brands": found.brands(),
        "mobile": found.mobile,
        "platform": found.platform_name,
        # Chrome on Android reports no architecture or bitness
        "architecture": "" if found.mobile else "arm" if arm else "x86",
        "bitness": "" if found.mobile else "64",
        "model": "",
        "platformVersion": str(nav.userAgentData.get("platformVersion") or found.platform_version),
        "uaFullVersion": found.browser_version or f"{found.major}.0.0.0",
        "fullVersionList": [
            {
                **b,
                "version": (found.browser_version or f"{b['version']}.0.0.0")
                if b["version"] == found.major
                else f"{b['version']}.0.0.0",
            }
            for b in found.brands()
        ],
        **{k: v for k, v in nav.userAgentData.items() if k not in _VERSIONED},
    }
    return Fingerprint(
        screen=ScreenFingerprint(
            availHeight=avail_h, availWidth=avail_w, availTop=0, availLeft=0, colorDepth=screen.colorDepth,
            height=screen.height, pixelDepth=screen.pixelDepth, width=screen.width,
            devicePixelRatio=screen.pixelRatio, pageXOffset=0, pageYOffset=0, innerHeight=inner_h,
            outerHeight=avail_h, outerWidth=avail_w, innerWidth=avail_w, screenX=0, clientWidth=avail_w,
            clientHeight=inner_h, hasHDR=False,
        ),
        navigator=NavigatorFingerprint(
            userAgent=nav.userAgent, userAgentData=cast(dict[str, str], ua_data), doNotTrack=nav.doNotTrack, appCodeName="Mozilla",
            appName="Netscape", appVersion=nav.userAgent.removeprefix("Mozilla/"), oscpu="", webdriver="false",
            language=nav.language, languages=nav.languages, platform=nav.platform, deviceMemory=nav.deviceMemory,
            hardwareConcurrency=nav.hardwareConcurrency, product="Gecko", productSub="20030107",
            vendor="Google Inc.", vendorSub="", maxTouchPoints=nav.maxTouchPoints, extraProperties={},
        ),
        headers=found.headers(),
        videoCodecs={"ogg": "", "h264": "probably", "webm": "probably"},
        audioCodecs={"ogg": "probably", "mp3": "probably", "wav": "probably", "m4a": "maybe", "aac": "probably"},
        pluginsData={},
        # browserforge's annotations are narrower than what its script reads (lists, numbers, null)
        battery=cast(dict[str, str], {"charging": True, "chargingTime": 0, "dischargingTime": None, "level": 1}),
        videoCard=VideoCard(renderer=found.webgl.renderer, vendor=found.webgl.vendor),
        multimediaDevices=[],
        fonts=found.fonts,
        mockWebRTC=False,  # a stub is a tell: WebRTC stays, kept to the proxy by the browser's policy (render.py)
        slim=False,
    )  # fmt: skip


_VERSIONED = ("mobile", "platform", "brands", "fullVersionList", "uaFullVersion")  # derived from the version


def generate(os: str, chrome: int | None, locale: str, time_zone: str) -> dict[str, Any]:
    """A new fingerprint file (format 2.0) from browserforge's generator — real-traffic combinations of hardware,
    screen, GPU and fonts. Its data lags behind Chrome releases: `chrome` moves it to that major version (the
    User-Agent, brands and client hints follow; the rest doesn't depend on it)."""
    from browserforge.fingerprints import FingerprintGenerator

    languages = [locale, locale.split("-")[0], "en-US", "en"] if not locale.startswith("en") else [locale, "en"]
    device = "mobile" if os == "android" else "desktop"
    made = FingerprintGenerator(browser="chrome", os=(os,), device=device, locale=tuple(languages)).generate()
    nav, screen = made.navigator, made.screen
    major = chrome or int(nav.userAgent.split("Chrome/")[1].split(".")[0])
    user_agent = re.sub(r"Chrome/[\d.]+", f"Chrome/{major}.0.0.0", nav.userAgent)
    ua_data = {
        k: v for k, v in dict(nav.userAgentData).items() if k not in ("brands", "fullVersionList", "uaFullVersion")
    }
    # the OS the proxy's TCP stack should look like: Windows 10 reports platformVersion 10.0.0, Windows 11 — 13+
    windows = "windows_10" if str(ua_data.get("platformVersion", "")).startswith("10.") else "windows_11"
    tcp = windows if os == "windows" else f"{os}_15"
    return {
        "geo": {"timezone": time_zone, "locale": locale},
        "os": os,
        "browser": "chrome",
        "browser_version": f"{major}.0.0.0",
        "navigator": {
            "userAgent": user_agent,
            "platform": nav.platform,
            "language": locale,
            "languages": languages,
            "hardwareConcurrency": nav.hardwareConcurrency,
            "deviceMemory": nav.deviceMemory,
            "maxTouchPoints": nav.maxTouchPoints,
            "doNotTrack": nav.doNotTrack,
            "userAgentData": ua_data,
        },
        "screen": {
            "width": screen.width, "height": screen.height, "availWidth": screen.availWidth,
            "availHeight": screen.availHeight, "colorDepth": screen.colorDepth, "pixelDepth": screen.pixelDepth,
            "pixelRatio": screen.devicePixelRatio,
        },
        "webgl": {"vendor": made.videoCard.vendor, "renderer": made.videoCard.renderer} if made.videoCard else {},
        "fonts": made.fonts,
        "timezone": {"name": time_zone},
        "_meta": {"version": "2.0", "engine": "chromium", "generator": "browserforge", "tcp_match": tcp},
    }  # fmt: skip


# --- consistency: one OS, one place --------------------------------------------------------------------

GEO_URL = "https://ipinfo.io/json"  # the exit IP's country and time zone, asked through the proxy (keyless)
_OS_SIGNS = {  # what gives each OS away in a fingerprint
    "windows": ("Windows NT", "Win", ("Direct3D",), ("Segoe UI", "Calibri", "Consolas", "Tahoma")),
    "macos": (
        "Macintosh",
        "Mac",
        ("Apple", "Metal", "Intel", "AMD"),
        ("Helvetica Neue", "Menlo", "Monaco", "Geneva", "Lucida Grande"),
    ),
    "linux": ("X11; Linux", "Linux x86", ("Mesa", "OpenGL", "Vulkan"), ("DejaVu Sans", "Liberation Sans", "Ubuntu")),
    "android": (
        "Android",
        "Linux arm",
        ("Adreno", "Mali", "PowerVR", "Xclipse", "Immortalis"),
        ("Roboto", "Droid Sans Mono", "Coming Soon", "Carrois Gothic SC"),
    ),
}
_LANGUAGE_OF = {"RU": "ru", "BY": "ru", "KZ": "ru", "UA": "uk", "US": "en", "GB": "en", "DE": "de", "FR": "fr"}


def _host_os() -> str:
    import sys

    return {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")


def os_issues(found: FingerprintFile, *, render: bool = False) -> list[str]:
    """Where the fingerprint contradicts its own OS (`os`, or the User-Agent's), and — rendering — this machine's.

    A site compares the User-Agent with navigator.platform, client hints, the GPU, the fonts it can measure and
    the proxy's TCP fingerprint (`_meta.tcp_match`, set at the proxy provider).
    """
    claimed = (found.os or "").lower() or next(
        (name for name, signs in _OS_SIGNS.items() if signs[0] in found.navigator.userAgent), "")  # fmt: skip
    if claimed not in _OS_SIGNS:
        return [f"unknown OS '{found.os}'"]
    ua_sign, platform_sign, gpu_signs, _ = _OS_SIGNS[claimed]
    issues = []
    if ua_sign not in found.navigator.userAgent:
        issues.append(f"User-Agent is not {claimed}'s: {found.navigator.userAgent}")
    if platform_sign.lower() not in found.navigator.platform.lower():
        issues.append(f"navigator.platform '{found.navigator.platform}' is not {claimed}'s")
    if found.navigator.userAgentData.get("platform") and found.platform_name.lower()[:3] != claimed[:3]:
        issues.append(f"client hints platform '{found.platform_name}' is not {claimed}")
    if found.webgl.renderer and not any(sign in found.webgl.renderer for sign in gpu_signs):
        issues.append(f"the GPU is not {claimed}'s: {found.webgl.renderer}")
    others = {f for name, signs in _OS_SIGNS.items() if name != claimed for f in signs[3]}
    if foreign := sorted(set(found.fonts) & others):
        issues.append(f"fonts of another OS: {', '.join(foreign)}")
    tcp = str(found.meta.get("tcp_match") or "")
    if tcp and not tcp.startswith(claimed):
        issues.append(f"the proxy's TCP fingerprint is set to {tcp}, not {claimed}")
    if render and claimed != _host_os():
        issues.append(f"rendering on {_host_os()}: the browser's real fonts and canvas are {_host_os()}'s, "
                      f"not {claimed}'s — crawl without rendering, or with a {_host_os()} fingerprint")  # fmt: skip
    return issues


def geo_issues(found: FingerprintFile, geo: dict[str, Any]) -> list[str]:
    """Where the fingerprint's place (time zone, language) contradicts the exit IP's (`geo`: country, timezone)."""
    issues = []
    zone = found.time_zone
    if geo.get("timezone") and zone and geo["timezone"] != zone:
        issues.append(f"time zone {zone}, but the IP {geo.get('ip', '')} is in {geo['timezone']}")
    language = _LANGUAGE_OF.get(str(geo.get("country") or ""))
    if language and not found.navigator.language.lower().startswith(language):
        issues.append(f"language {found.navigator.language}, but the IP is in {geo.get('country')}")
    country = found.geo.country_iso
    if country and geo.get("country") and country != geo["country"]:
        issues.append(f"made for {country}, but the IP is in {geo['country']}")
    return issues


async def exit_geo(client: Any, proxy_info: Any, timeout_s: float) -> dict[str, Any] | None:
    """The exit IP's country and time zone — through the proxy, the way the site sees it; None — no answer."""
    from datetime import timedelta

    try:
        response = await client.send_request(GEO_URL, proxy_info=proxy_info, timeout=timedelta(seconds=timeout_s))
        data = json.loads(await response.read())
    except Exception:
        return None
    return data if isinstance(data, dict) and response.status_code == 200 else None


async def prepare(settings: CrawlSettings, found: FingerprintFile | None, client: Any, proxy_info: Any,
                  render: bool) -> FingerprintFile | None:  # fmt: skip
    """The fingerprint for this crawl, checked (crawl.fingerprint_check) against its OS, this machine and the
    exit IP; with crawl.fingerprint_timezone = ip its time zone is the exit IP's.

    warn — log the issues; stop — raise FingerprintMismatch; off — no check. The exit IP's place is asked from
    GEO_URL through the proxy only when the check or the time zone needs it.
    """
    if found is None:
        return None
    wants_ip_zone = settings.fingerprint_timezone == "ip"
    geo = None
    if settings.fingerprint_check != "off" or wants_ip_zone:
        geo = await exit_geo(client, proxy_info, settings.timeout_s)
        if geo is None:
            log.warning("fingerprint: couldn't learn where the exit IP is (%s)", GEO_URL)
    if wants_ip_zone and geo and geo.get("timezone"):
        found = with_timezone(found, str(geo["timezone"]))
    if settings.fingerprint_check == "off":
        return found
    issues = os_issues(found, render=render) + (geo_issues(found, geo) if geo else [])
    if issues and settings.fingerprint_check == "stop":
        raise FingerprintMismatch(issues)
    for issue in issues:
        log.warning("fingerprint %s: %s", settings.fingerprint, issue)
    return found


def with_timezone(found: FingerprintFile, zone: str) -> FingerprintFile:
    """The same fingerprint in another time zone (the exit IP's)."""
    return found.model_copy(
        update={"timezone": TimeZone(name=zone), "geo": found.geo.model_copy(update={"timezone": zone})}
    )


async def ip_timezone(client: Any, proxy_info: Any, timeout_s: float) -> str | None:
    """The exit IP's time zone — after an IP change the modem may be in another region."""
    geo = await exit_geo(client, proxy_info, timeout_s)
    return str(geo["timezone"]) if geo and geo.get("timezone") else None


def summary(found: FingerprintFile, path: Path) -> dict[str, Any]:
    """What `spider fingerprints show` reports: what goes where, and what isn't faked."""
    return {
        "path": str(path),
        "ip": found.ip,
        "headers": found.headers(),
        "browser": {
            "platform": found.navigator.platform,
            "languages": found.navigator.languages,
            "hardware_concurrency": found.navigator.hardwareConcurrency,
            "device_memory": found.navigator.deviceMemory,
            "screen": f"{found.screen.width}x{found.screen.height}@{found.screen.pixelRatio}",
            "webgl": found.webgl.renderer,
            "timezone": found.time_zone,
            "locale": found.locale,
            "webrtc": "proxied only",
        },
        "not_faked": ["canvas", "audio", "fonts", "TLS of plain requests (impit's own Chrome)"],
    }
