"""The polygon: a tiny local site whose pages are traps for the crawler's checks.

Each route is (status, headers, html). Ordinary pages are "clean" — a title, description, h1 and
h2 of acceptable length, unique per page — so every issue rule reports exactly its own traps
(EXPECTED_ISSUES). Add a trap page per new check and its expected paths. The server runs in its
own thread and event loop, because the crawler under test calls `asyncio.run` itself.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from aiohttp import web

TITLE = "Полигон spider: страница {} для проверок"  # 30–60 characters
DESCRIPTION = "Описание страницы {} полигона spider: достаточно длинное, чтобы уложиться в норму сниппета."
H1 = "Заголовок страницы {}"
H2 = "Раздел страницы {}"


def _links(links: tuple[str, ...]) -> str:
    return "".join(f'<a href="{href}">{href}</a>' for href in links)


def _html(slug: str, *links: str, head: str | None = None, body: str | None = None) -> str:
    """A clean page; `head` / `body` replace the default elements to build a trap."""
    if head is None:
        head = f'<title>{TITLE.format(slug)}</title><meta name="description" content="{DESCRIPTION.format(slug)}">'
    if body is None:
        body = f"<h1>{H1.format(slug)}</h1><h2>{H2.format(slug)}</h2>"
    return f"<html><head>{head}</head><body>{body}{_links(links)}</body></html>"


def _head(slug: str, *, title: str | None = None, description: str | None = None, extra: str = "") -> str:
    title = TITLE.format(slug) if title is None else title
    description = DESCRIPTION.format(slug) if description is None else description
    return f'<title>{title}</title><meta name="description" content="{description}">{extra}'


def _no_title(slug: str) -> str:
    return f'<meta name="description" content="{DESCRIPTION.format(slug)}">'


def _no_description(slug: str) -> str:
    return f"<title>{TITLE.format(slug)}</title>"


ONPAGE_TRAPS: dict[str, str] = {
    # Page Titles
    "/t-missing": _html("t-missing", head=_head("t-missing", title="")),
    "/t-multiple": _html("t-multiple", head=_head("t-multiple", extra="<title>Второй title на странице</title>")),
    "/t-outside": _html(
        "t-outside", head=_no_title("t-outside"), body=f"<title>{TITLE.format('t-outside')}</title><h1>t</h1><h2>t</h2>"
    ),
    "/t-long": _html("t-long", head=_head("t-long", title="Очень длинный заголовок страницы " * 3)),
    "/t-short": _html("t-short", head=_head("t-short", title="Коротко")),
    "/t-same-h1": _html(
        "t-same-h1",
        head=_head("t-same-h1", title="Одинаковые заголовок и H1 на этой странице"),
        body="<h1>Одинаковые заголовок и H1 на этой странице</h1><h2>Раздел</h2>",
    ),
    # Meta Description
    "/d-multiple": _html(
        "d-multiple", head=_head("d-multiple", extra=f'<meta name="description" content="{DESCRIPTION.format("x")}">')
    ),
    "/d-outside": _html(
        "d-outside",
        head=_no_description("d-outside"),
        body=f'<meta name="description" content="{DESCRIPTION.format("d-outside")}"><h1>d</h1><h2>d</h2>',
    ),
    "/d-missing": _html("d-missing", head=_no_description("d-missing")),
    "/d-long": _html("d-long", head=_head("d-long", description="Слишком подробное описание. " * 8)),
    "/d-short": _html("d-short", head=_head("d-short", description="Коротко.")),
    # H1
    "/h1-missing": _html("h1-missing", body=f"<h2>{H2.format('h1-missing')}</h2>"),  # h2 without h1: non-sequential too
    "/h1-multiple": _html("h1-multiple", body="<h1>Первый H1</h1><h1>Второй H1</h1><h2>Раздел h1-multiple</h2>"),
    "/h1-alt": _html("h1-alt", body='<h1><img src="/logo.png" alt="Логотип магазина"></h1><h2>Раздел h1-alt</h2>'),
    "/h1-nonseq": _html("h1-nonseq", body="<h3>Сначала h3</h3><h1>Потом H1 h1-nonseq</h1><h2>Раздел h1-nonseq</h2>"),
    "/h1-long": _html("h1-long", body=f"<h1>{'Очень длинный главный заголовок ' * 3}</h1><h2>Раздел h1-long</h2>"),
    # H2
    "/h2-missing": _html("h2-missing", body=f"<h1>{H1.format('h2-missing')}</h1>"),
    "/h2-multiple": _html("h2-multiple", body="<h1>H1 h2-multiple</h1><h2>Первый раздел</h2><h2>Второй раздел</h2>"),
    "/h2-nonseq": _html("h2-nonseq", body="<h1>H1 h2-nonseq</h1><h3>Пропущен уровень</h3><h2>Раздел h2-nonseq</h2>"),
    "/h2-long": _html("h2-long", body=f"<h1>H1 h2-long</h1><h2>{'Очень длинный подзаголовок раздела ' * 3}</h2>"),
}

ROUTES: dict[str, tuple[int, dict[str, str], str]] = {
    "/": (
        200,
        {},
        _html(
            "home",
            "/a",
            "/b",
            "/b?sort=price",  # same page as /b under another URL: the duplicate-content trap
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
            *ONPAGE_TRAPS,
        ),
    ),
    "/a": (200, {}, _html("a", "/c")),
    "/b": (200, {}, _html("b", "/")),
    "/c": (200, {}, _html("c")),
    "/old": (301, {"Location": "/a"}, ""),
    "/missing": (404, {}, "<html><body>Не найдено</body></html>"),
    # --- Response Codes traps ---
    "/robots.txt": (200, {"Content-Type": "text/plain"}, "User-agent: *\nDisallow: /private/\n"),
    "/private/secret": (200, {}, _html("secret")),  # never fetched: disallowed
    "/error": (500, {}, "<html><body>Ошибка сервера</body></html>"),
    "/chain1": (301, {"Location": "/chain2"}, ""),
    "/chain2": (302, {"Location": "/a"}, ""),
    "/loop1": (301, {"Location": "/loop2"}, ""),
    "/loop2": (301, {"Location": "/loop1"}, ""),
    "/to-missing": (301, {"Location": "/missing"}, ""),  # a redirect that lands on an error
    "/meta-refresh": (
        200,
        {},
        _html("meta-refresh", head=_head("meta-refresh", extra='<meta http-equiv="refresh" content="0; url=/c">')),
    ),
    "/http-refresh": (200, {"Refresh": "0; url=/c"}, _html("http-refresh")),
    # "/reset" closes the connection without answering (see _handle)
    **{path: (200, {}, html) for path, html in ONPAGE_TRAPS.items()},
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
    *ONPAGE_TRAPS,
}

DUPLICATES = {"/b", "/b?sort=price"}

# issue code -> polygon paths the rule must report (and nothing else).
EXPECTED_ISSUES = {
    # Response Codes
    "internal_no_response": {"/reset"},
    "internal_client_error": {"/missing"},
    "internal_server_error": {"/error"},
    "internal_redirect_loop": {"/loop1", "/loop2"},
    "internal_blocked_by_robots": {"/private/secret"},
    "internal_redirect_chain": {"/chain1"},
    "internal_redirection_3xx": {"/old", "/chain1", "/chain2", "/loop1", "/loop2", "/to-missing"},
    "internal_redirection_meta_refresh": {"/meta-refresh"},
    "internal_redirection_http_refresh": {"/http-refresh"},
    # Page Titles
    "page_title_missing": {"/t-missing"},
    "page_title_multiple": {"/t-multiple"},
    "page_title_outside_head": {"/t-outside"},
    "page_title_duplicate": DUPLICATES,
    "page_title_over_max": {"/t-long"},
    "page_title_below_min": {"/t-short"},
    "page_title_same_as_h1": {"/t-same-h1"},
    # Meta Description
    "meta_description_multiple": {"/d-multiple"},
    "meta_description_outside_head": {"/d-outside"},
    "meta_description_missing": {"/d-missing"},
    "meta_description_duplicate": DUPLICATES,
    "meta_description_over_max": {"/d-long"},
    "meta_description_below_min": {"/d-short"},
    # H1
    "h1_missing": {"/h1-missing"},
    "h1_multiple": {"/h1-multiple"},
    "h1_alt_text": {"/h1-alt"},
    "h1_non_sequential": {"/h1-nonseq"},
    "h1_duplicate": DUPLICATES,
    "h1_over_max": {"/h1-long"},
    # H2
    "h2_missing": {"/h2-missing"},
    "h2_multiple": {"/h2-multiple"},
    "h2_non_sequential": {"/h2-nonseq", "/h1-missing"},
    "h2_duplicate": DUPLICATES,
    "h2_over_max": {"/h2-long"},
}

SEEN_USER_AGENTS: set[str] = set()  # what reached the server — proves crawl.user_agent is sent


async def _handle(request: web.Request) -> web.StreamResponse:
    SEEN_USER_AGENTS.add(request.headers.get("User-Agent", ""))
    if request.path == "/reset":  # no response at all: the client sees a dropped connection
        assert request.transport is not None
        request.transport.abort()
        return web.Response()
    status, headers, body = ROUTES.get(request.path, (404, {}, "<html><body>Не найдено</body></html>"))
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
