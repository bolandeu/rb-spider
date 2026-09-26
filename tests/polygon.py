"""The polygon: a tiny local site whose pages are traps for the crawler's checks.

Each route is (status, headers, html). Add a trap page per check from docs/features.md and a
test that the check finds it. The server runs in its own thread and event loop, because the
crawler under test calls `asyncio.run` itself.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from aiohttp import web


def _html(title: str, *links: str) -> str:
    anchors = "".join(f'<a href="{href}">{href}</a>' for href in links)
    return f"<html><head><title>{title}</title></head><body>{anchors}</body></html>"


ROUTES: dict[str, tuple[int, dict[str, str], str]] = {
    "/": (
        200,
        {},
        _html(
            "Главная",
            "/a",
            "/b",
            "/b?sort=price",  # a distinct URL with the same path
            "/a#reviews",  # same page as /a: the fragment must be dropped
            "/old",
            "/missing",
            "https://external.example/",  # another host: recorded as a link, never crawled
            "mailto:shop@example.com",  # not http(s): ignored
        ),
    ),
    "/a": (200, {}, _html("Страница A", "/c")),
    "/b": (200, {}, _html("Страница B", "/")),
    "/c": (200, {}, _html("Страница C")),
    "/old": (301, {"Location": "/a"}, ""),
    "/missing": (404, {}, _html("Не найдено")),
}

# URLs a full crawl of the polygon must reach (paths relative to the polygon's base URL).
REACHABLE = {"/", "/a", "/b", "/b?sort=price", "/c", "/old", "/missing"}


async def _handle(request: web.Request) -> web.Response:
    status, headers, body = ROUTES.get(request.path, (404, {}, _html("Не найдено")))
    return web.Response(status=status, headers=headers, text=body, content_type="text/html")


@contextmanager
def serve() -> Iterator[str]:
    """Run the polygon on a free local port; yields its base URL (no trailing slash)."""
    loop = asyncio.new_event_loop()
    app = web.Application()
    app.router.add_get("/{tail:.*}", _handle)
    runner = web.AppRunner(app, access_log=None)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, "127.0.0.1", 0)
    loop.run_until_complete(site.start())
    port = runner.addresses[0][1]
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.run_until_complete(runner.cleanup())
        loop.close()
