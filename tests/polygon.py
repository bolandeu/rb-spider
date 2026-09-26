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
            "/private/secret",
            "/error",
            "/chain1",
            "/loop1",
            "/meta-refresh",
            "/http-refresh",
            "/reset",
            "/to-missing",
        ),
    ),
    "/a": (200, {}, _html("Страница A", "/c")),
    "/b": (200, {}, _html("Страница B", "/")),
    "/c": (200, {}, _html("Страница C")),
    "/old": (301, {"Location": "/a"}, ""),
    "/missing": (404, {}, _html("Не найдено")),
    # --- traps: one per issue rule (EXPECTED_ISSUES below) ---
    "/robots.txt": (200, {"Content-Type": "text/plain"}, "User-agent: *\nDisallow: /private/\n"),
    "/private/secret": (200, {}, _html("Секрет")),  # never fetched: disallowed
    "/error": (500, {}, _html("Ошибка сервера")),
    "/chain1": (301, {"Location": "/chain2"}, ""),
    "/chain2": (302, {"Location": "/a"}, ""),
    "/loop1": (301, {"Location": "/loop2"}, ""),
    "/loop2": (301, {"Location": "/loop1"}, ""),
    "/to-missing": (301, {"Location": "/missing"}, ""),  # a redirect that lands on an error
    "/meta-refresh": (200, {}, '<html><head><meta http-equiv="refresh" content="0; url=/c"></head></html>'),
    "/http-refresh": (200, {"Refresh": "0; url=/c"}, _html("Обновление заголовком")),
    # "/reset" closes the connection without answering (see _handle)
}

# URLs a full crawl of the polygon must reach (paths relative to the polygon's base URL).
REACHABLE = {
    "/",
    "/a",
    "/b",
    "/b?sort=price",
    "/c",
    "/old",
    "/missing",
    "/private/secret",
    "/error",
    "/chain1",
    "/chain2",
    "/loop1",
    "/loop2",
    "/meta-refresh",
    "/http-refresh",
    "/reset",
    "/to-missing",
}

# issue code -> polygon paths the rule must report (and nothing else).
EXPECTED_ISSUES = {
    "internal_no_response": {"/reset"},
    "internal_client_error": {"/missing"},
    "internal_server_error": {"/error"},
    "internal_redirect_loop": {"/loop1", "/loop2"},
    "internal_blocked_by_robots": {"/private/secret"},
    "internal_redirect_chain": {"/chain1"},
    "internal_redirection_3xx": {"/old", "/chain1", "/chain2", "/loop1", "/loop2", "/to-missing"},
    "internal_redirection_meta_refresh": {"/meta-refresh"},
    "internal_redirection_http_refresh": {"/http-refresh"},
}


SEEN_USER_AGENTS: set[str] = set()  # what reached the server — proves crawl.user_agent is sent


async def _handle(request: web.Request) -> web.StreamResponse:
    SEEN_USER_AGENTS.add(request.headers.get("User-Agent", ""))
    if request.path == "/reset":  # no response at all: the client sees a dropped connection
        assert request.transport is not None
        request.transport.abort()
        return web.Response()
    status, headers, body = ROUTES.get(request.path, (404, {}, _html("Не найдено")))
    headers = {"Content-Type": "text/html; charset=utf-8", **headers}
    return web.Response(status=status, headers=headers, text=body)


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
