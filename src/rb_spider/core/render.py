"""JS rendering (`crawl.render = "always"`): an HTML page's DOM after the browser ran its scripts.

Hybrid, as in Screaming Frog: the crawl still fetches every URL over HTTP — status codes, headers and
each redirect step stay exact, resources are checked without a browser — and only HTML pages that
answered 200 are opened in a browser as well; the SEO data is read from the rendered DOM by the same
`extract.parse_page`. The browser is Playwright managed by Crawlee's `BrowserPool`, and it is an
optional extra (`rb-spider[render]`): a crawl without rendering never imports it.
"""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import Any

from .errors import RenderUnavailable

log = logging.getLogger(__name__)

# The DOM doesn't need these, and skipping them makes rendering several times faster.
_SKIPPED_RESOURCES = {"image", "media", "font"}


def ensure_available() -> None:
    """Fail early (before a crawl is registered) when the `render` extra isn't installed."""
    try:
        import playwright  # noqa: F401
    except ImportError as exc:
        raise RenderUnavailable("Playwright is not installed.") from exc


class Renderer:
    """At most `tabs` pages open at once; each waits for `load`, then `wait_ms` more for late scripts."""

    def __init__(
        self, *, tabs: int, wait_ms: int, timeout_s: float, user_agent: str | None, headers: dict[str, str]
    ) -> None:
        self.tabs, self.wait_ms, self.timeout_ms = tabs, wait_ms, timeout_s * 1000
        self.context_options: dict[str, Any] = {"extra_http_headers": headers} if headers else {}
        if user_agent:
            self.context_options["user_agent"] = user_agent
        self._slots = asyncio.Semaphore(tabs)
        self._pool: Any = None

    async def __aenter__(self) -> Renderer:
        ensure_available()
        from crawlee.browsers import BrowserPool, PlaywrightBrowserPlugin  # optional extra

        plugin = PlaywrightBrowserPlugin(
            browser_launch_options={"headless": True},
            browser_new_context_options=self.context_options,
            max_open_pages_per_browser=self.tabs,
        )
        pool = BrowserPool([plugin])
        self._pool = await pool.__aenter__()
        try:  # the pool starts a browser lazily: open a tab now, or a missing browser would look like dead pages
            await (await self._pool.new_page()).page.close()
        except Exception as exc:
            await self._pool.__aexit__(None, None, None)
            self._pool = None
            raise RenderUnavailable(f"the browser could not start ({str(exc).splitlines()[0]}).") from exc
        return self

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
