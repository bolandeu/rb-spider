"""JS rendering (`crawl.render = "always"`): an HTML page's DOM after the browser ran its scripts.

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
from pathlib import Path
from types import TracebackType
from typing import Any

from .errors import RenderUnavailable

log = logging.getLogger(__name__)

# The DOM doesn't need these, and skipping them makes rendering several times faster.
_SKIPPED_RESOURCES = {"image", "media", "font"}


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


class Renderer:
    """At most `tabs` pages open at once; each waits for `load`, then `wait_ms` more for late scripts."""

    def __init__(
        self,
        *,
        tabs: int,
        wait_ms: int,
        timeout_s: float,
        user_agent: str | None,
        headers: dict[str, str],
        browser: str | None = None,
    ) -> None:
        self.tabs, self.wait_ms, self.timeout_ms, self.browser = tabs, wait_ms, timeout_s * 1000, browser
        self.used_browser: str | None = None
        self.context_options: dict[str, Any] = {"extra_http_headers": headers} if headers else {}
        if user_agent:
            self.context_options["user_agent"] = user_agent
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

    async def __aexit__(self, *exc: type[BaseException] | BaseException | TracebackType | None) -> None:
        if self._pool is not None:
            await self._pool.__aexit__(None, None, None)

    async def render(self, url: str) -> bytes | None:
        """The rendered HTML, or None when the page couldn't be rendered (the crawl keeps the raw HTML)."""
        async with self._slots:
            page = None
            try:
                page = (await self._pool.new_page()).page
                await page.route("**/*", _skip_heavy)
                await page.goto(url, wait_until="load", timeout=self.timeout_ms)
                if self.wait_ms:
                    await page.wait_for_timeout(self.wait_ms)
                return (await page.content()).encode()
            except Exception as exc:  # timeout, crash, navigation error: data, not a failed crawl
                log.warning("rendering %s failed: %s", url, str(exc).splitlines()[0] if str(exc) else type(exc))
                return None
            finally:
                if page is not None:
                    await page.close()


async def _skip_heavy(route: Any) -> None:
    if route.request.resource_type in _SKIPPED_RESOURCES:
        await route.abort()
    else:
        await route.continue_()
