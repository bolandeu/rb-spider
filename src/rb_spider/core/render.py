"""JS rendering (`crawl.render = "always"` or `"auto"`): an HTML page's DOM after the browser ran its scripts, and
what the browser saw meanwhile — console errors, resources it couldn't load, where the page ended up.

Hybrid, as in Screaming Frog: the crawl still fetches every URL over HTTP — status codes, headers and
each redirect step stay exact, resources are checked without a browser — and only HTML pages that
answered 200 are opened in a browser as well; the SEO data is read from the rendered DOM by the same
`extract.parse_page`. The browser is Playwright managed by Crawlee's `BrowserPool` (the plugin
`PlaywrightCrawler` itself uses), and it is an optional extra (`rb-spider[render]`).

Which browser: `crawl.render_browser` if set; else Playwright's own build for its version; else the
newest Chromium already in Playwright's cache (other tools' Playwright versions leave builds there);
else the installed Google Chrome. Each Playwright release wants its own build, so without this a
machine full of browsers would still need another download.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from .errors import RenderUnavailable

log = logging.getLogger(__name__)

# The DOM doesn't need these, and skipping them makes rendering several times faster.
_SKIPPED_RESOURCES = {"image", "media", "font"}
# crawl.render_viewport presets: (width, height, mobile). Mobile — Googlebot Smartphone's screen, with touch.
VIEWPORTS = {"desktop": (1366, 768, False), "mobile": (411, 731, True)}
_MAX_EVENTS = 50  # console messages and failed resources kept per page: a broken page can log thousands

# Shadow roots aren't part of page.content(): each is copied into its host as a <div data-spider-shadow>, innermost
# first, so the text and links web components draw are read like any other.
_FLATTEN_SHADOW = """() => {
  const flatten = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (!el.shadowRoot) continue;
      flatten(el.shadowRoot);
      const copy = document.createElement('div');
      copy.setAttribute('data-spider-shadow', '');
      copy.innerHTML = el.shadowRoot.innerHTML;
      el.appendChild(copy);
    }
  };
  flatten(document);
}"""
_INSERT_FRAME = """(el, html) => {
  const copy = document.createElement('div');
  copy.setAttribute('data-spider-iframe', el.getAttribute('src') || '');
  copy.innerHTML = html;
  el.after(copy);
}"""


# Images as laid out (only loaded ones: an image the browser skipped has no real size) and CSS background images.
_IMAGES = """(limit) => {
  const images = [];
  for (const img of document.images) {
    if (images.length >= limit) break;
    if (!img.complete || !img.naturalWidth) continue;
    const box = img.getBoundingClientRect();
    images.push([img.currentSrc || img.src, img.naturalWidth, img.naturalHeight,
                 Math.round(box.width), Math.round(box.height)]);
  }
  const backgrounds = new Set();
  for (const el of document.querySelectorAll('*')) {
    if (backgrounds.size >= limit) break;
    const value = getComputedStyle(el).backgroundImage;
    if (!value || value === 'none') continue;
    for (const m of value.matchAll(/url\\(["']?([^"')]+)["']?\\)/g)) {
      if (m[1].startsWith('http')) backgrounds.add(m[1]);
    }
  }
  return {images, backgrounds: [...backgrounds]};
}"""
_MAX_IMAGES = 200  # per page: <img> sizes and background images


@dataclass
class Rendered:
    """What the browser made of a page."""

    html: bytes
    final_url: str  # where the page ended up: another URL than requested — JavaScript navigated away
    console: list[tuple[str, str]] = field(default_factory=list)  # (error | warning, text): console and exceptions
    resources: list[tuple[str, str]] = field(default_factory=list)  # (URL, robots.txt | failed: … | HTTP 404)
    # loaded <img>: (URL, real width, real height, display width, display height) — crawl.render_images
    images: list[tuple[str, int, int, int, int]] = field(default_factory=list)
    backgrounds: list[str] = field(default_factory=list)  # CSS background-image URLs (computed styles)
    screenshot: bytes | None = None  # the first screen as JPEG (crawl.render_screenshots)


def same_page(a: str, b: str) -> bool:
    """Two URLs of one document: they differ at most in the #fragment."""
    x, y = urlsplit(a), urlsplit(b)
    return urlunsplit((*x[:4], "")) == urlunsplit((*y[:4], ""))


def ensure_available() -> None:
    """Fail early (before a crawl is registered) when the `render` extra isn't installed."""
    if importlib.util.find_spec("playwright") is None:
        raise RenderUnavailable("Playwright is not installed.")


_EXECUTABLES = (
    "chrome-headless-shell",
    "chrome-headless-shell.exe",
    "Google Chrome for Testing",
    "chrome",
    "chrome.exe",
)


def _playwright_cache() -> Path:
    explicit = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if explicit and explicit != "0":
        return Path(explicit)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ms-playwright"


def cached_browsers(cache: Path | None = None) -> list[Path]:
    """Chromium builds in Playwright's cache, newest first (headless shell before the full browser)."""
    cache = cache or _playwright_cache()
    builds = []
    for build in cache.glob("chromium*-*") if cache.is_dir() else []:
        match = re.fullmatch(r"chromium(_headless_shell)?-(\d+)", build.name)
        if match:
            builds.append((int(match.group(2)), match.group(1) is not None, build))
    found = []
    for _, _, build in sorted(builds, reverse=True):
        executable = next((p for name in _EXECUTABLES for p in build.rglob(name) if p.is_file()), None)
        if executable is not None:
            found.append(executable)
    return found


def _launch_choices(explicit: str | None) -> list[tuple[str, dict]]:
    """(label, PlaywrightBrowserPlugin options) to try in order."""
    if explicit:
        return [(explicit, {"executable_path": explicit})]
    return [
        ("playwright chromium", {}),
        *((str(path), {"executable_path": str(path)}) for path in cached_browsers()),
        ("google chrome", {"browser_type": "chrome"}),
    ]


def proxy_settings(url: str) -> dict[str, str]:
    """A proxy URL as Playwright's context option: the server apart from its login and password."""
    parts = urlsplit(url)
    found = {
        "server": f"{parts.scheme}://{parts.hostname}:{parts.port}"
        if parts.port
        else f"{parts.scheme}://{parts.hostname}"
    }
    if parts.username:
        found["username"] = unquote(parts.username)
    if parts.password:
        found["password"] = unquote(parts.password)
    return found


def viewport_options(viewport: str) -> dict[str, Any]:
    """Browser context options for crawl.render_viewport: a preset (desktop, mobile) or WIDTHxHEIGHT."""
    if viewport in VIEWPORTS:
        width, height, mobile = VIEWPORTS[viewport]
    else:
        width, height = (int(n) for n in viewport.lower().split("x"))
        mobile = False
    options: dict[str, Any] = {"viewport": {"width": width, "height": height}}
    if mobile:
        options |= {"is_mobile": True, "has_touch": True, "device_scale_factor": 2.625}
    return options


class Renderer:
    """At most `tabs` pages open at once; each waits for `load`, then `wait_ms` more for late scripts.

    `allowed` — robots.txt for the page's own requests: a disallowed script or stylesheet isn't loaded (as
    Googlebot wouldn't) and is reported (Pages with Blocked Resources).
    """

    def __init__(
        self,
        *,
        tabs: int,
        wait_ms: int,
        timeout_s: float,
        user_agent: str | None,
        headers: dict[str, str],
        browser: str | None = None,
        viewport: str = "desktop",
        console: bool = True,
        flatten_shadow_dom: bool = True,
        flatten_iframes: bool = True,
        images: bool = False,
        screenshots: bool = False,
        allowed: Callable[[str], Awaitable[bool]] | None = None,
        proxy: str | None = None,
    ) -> None:
        self.tabs, self.wait_ms, self.timeout_ms, self.browser = tabs, wait_ms, timeout_s * 1000, browser
        self.console, self.flatten_shadow_dom, self.flatten_iframes = console, flatten_shadow_dom, flatten_iframes
        self.allowed, self.screenshots = allowed, screenshots
        # images load only when their real vs display size is wanted: skipping them makes rendering much faster
        self.skipped = _SKIPPED_RESOURCES - {"image"} if images else _SKIPPED_RESOURCES
        self.used_browser: str | None = None
        self.context_options: dict[str, Any] = viewport_options(viewport)
        if headers:
            self.context_options["extra_http_headers"] = headers
        if user_agent:
            self.context_options["user_agent"] = user_agent
        if proxy:
            self.context_options["proxy"] = proxy_settings(proxy)
        self._slots = asyncio.Semaphore(tabs)
        self._pool: Any = None

    async def __aenter__(self) -> Renderer:
        ensure_available()
        from crawlee.browsers import BrowserPool, PlaywrightBrowserPlugin  # optional extra

        errors = []
        for label, options in _launch_choices(self.browser):
            launch = {
                "headless": True,
                **({"executable_path": options["executable_path"]} if "executable_path" in options else {}),
            }
            plugin = PlaywrightBrowserPlugin(
                browser_type=options.get("browser_type", "chromium"),
                browser_launch_options=launch,
                browser_new_context_options=self.context_options,
                max_open_pages_per_browser=self.tabs,
            )
            pool = await BrowserPool([plugin]).__aenter__()
            try:  # the pool starts a browser lazily: open a tab now, or a missing browser would look like dead pages
                await (await pool.new_page()).page.close()
            except Exception as exc:
                await pool.__aexit__(None, None, None)
                errors.append(f"{label}: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}")
                continue
            self._pool, self.used_browser = pool, label
            log.info("rendering with %s", label)
            return self
        raise RenderUnavailable(f"no browser could start ({'; '.join(errors)}).")

    async def use_proxy(self, url: str | None) -> None:
        """Another proxy, or none (the crawl dropped a dead one): a new browser; pages open in the old one fail."""
        if self._pool is None or self.context_options.get("proxy") == (proxy_settings(url) if url else None):
            return
        self.context_options.pop("proxy", None)
        if url:
            self.context_options["proxy"] = proxy_settings(url)
        old = self._pool
        await self.__aenter__()
        await old.__aexit__(None, None, None)

    async def __aexit__(self, *exc: type[BaseException] | BaseException | TracebackType | None) -> None:
        if self._pool is not None:
            await self._pool.__aexit__(None, None, None)

    async def render(self, url: str) -> Rendered | None:
        """The rendered page, or None when it couldn't be rendered (the crawl keeps the raw HTML)."""
        async with self._slots:
            page = None
            console: list[tuple[str, str]] = []
            resources: list[tuple[str, str]] = []
            aborted: set[str] = set()

            def note(target: list, item: tuple[str, str]) -> None:
                if len(target) < _MAX_EVENTS:
                    target.append(item)

            async def route(route: Any) -> None:
                request = route.request
                if (self.allowed is not None and request.url.startswith("http") and not same_page(request.url, url)
                        and not await self.allowed(request.url)):  # fmt: skip
                    aborted.add(request.url)
                    note(resources, (request.url, "robots.txt"))
                    await route.abort()
                elif request.resource_type in self.skipped:
                    aborted.add(request.url)
                    await route.abort()
                else:
                    await route.continue_()

            def logged(message: Any) -> None:
                if message.type not in ("error", "warning"):
                    return
                if (message.location or {}).get("url") in aborted:  # "Failed to load resource": our own abort
                    return
                note(console, (message.type, message.text[:1000]))

            def failed(request: Any) -> None:
                if request.url not in aborted and request.url.startswith("http"):
                    note(resources, (request.url, f"failed: {request.failure or 'error'}"[:300]))

            def responded(response: Any) -> None:
                if response.status >= 400 and not same_page(response.url, url):
                    note(resources, (response.url, f"HTTP {response.status}"))

            try:
                page = (await self._pool.new_page()).page
                await page.route("**/*", route)
                if self.console:
                    page.on("console", logged)
                    page.on("pageerror", lambda exc: note(console, ("error", str(exc)[:1000])))
                page.on("requestfailed", failed)
                page.on("response", responded)
                await page.goto(url, wait_until="load", timeout=self.timeout_ms)
                if self.wait_ms:
                    await page.wait_for_timeout(self.wait_ms)
                await page.wait_for_load_state("load", timeout=self.timeout_ms)  # a script may have navigated away
                if self.flatten_iframes:
                    await _flatten_frames(page)
                if self.flatten_shadow_dom:
                    await page.evaluate(_FLATTEN_SHADOW)
                found = await page.evaluate(_IMAGES, _MAX_IMAGES)
                html = (await page.content()).encode()
                images = [tuple(row) for row in found["images"]]
                shot = await page.screenshot(type="jpeg", quality=70) if self.screenshots else None
                return Rendered(html, page.url, console, resources, images, found["backgrounds"], shot)
            except Exception as exc:  # timeout, crash, navigation error: data, not a failed crawl
                log.warning("rendering %s failed: %s", url, str(exc).splitlines()[0] if str(exc) else type(exc))
                return None
            finally:
                if page is not None:
                    await page.close()


async def _flatten_frames(page: Any) -> None:
    """Each iframe's body copied after its <iframe> element, deepest frames first (Flatten iframes)."""
    frames = [f for f in page.frames if f.parent_frame is not None]
    depth = {f: 0 for f in frames}
    for frame in frames:
        parent = frame.parent_frame
        while parent is not None and parent.parent_frame is not None:
            depth[frame] += 1
            parent = parent.parent_frame
    for frame in sorted(frames, key=lambda f: -depth[f]):
        try:
            html = await frame.evaluate("() => document.body ? document.body.innerHTML : ''")
            element = await frame.frame_element()
            await element.evaluate(_INSERT_FRAME, html)
        except Exception:  # a frame that navigated or closed meanwhile: left out  # noqa: S112
            continue
