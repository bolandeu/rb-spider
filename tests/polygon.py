"""The polygon: a tiny local site whose pages are traps for the crawler's checks.

Each route is (status, headers, html). Ordinary pages are "clean" — a title, description, h1 and
h2 of acceptable length, unique per page — so every issue rule reports exactly its own traps
(EXPECTED_ISSUES). Add a trap page per new check and its expected paths. The server runs in its
own thread and event loop, because the crawler under test calls `asyncio.run` itself.
"""

from __future__ import annotations

import asyncio
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import PurePosixPath

import trustme
from aiohttp import web

TITLE = "Полигон spider: страница {} для проверок"  # 30–60 characters
DESCRIPTION = "Описание страницы {} полигона spider: достаточно длинное, чтобы уложиться в норму сниппета."
H1 = "Заголовок страницы {}"
H2 = "Раздел страницы {}"
VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'
FILLER = "<p>" + "Это простой текст для полигона и он легко читается. " * 30 + "</p>"  # 270 easy words


def _links(links: tuple[str, ...]) -> str:
    return "".join(f'<a href="{href}">{href}</a>' for href in links)


def _html(
    slug: str, *links: str, head: str | None = None, body: str | None = None, thin: bool = False, dead_end: bool = False
) -> str:
    """A clean page; `head` / `body` replace the default elements to build a trap, `thin` drops the text.

    A page without `links` links back home — a page with no internal links is a trap of its own (`dead_end`).
    """
    if not links and not dead_end:
        links = ("/",)
    if head is None:
        head = f'<title>{TITLE.format(slug)}</title><meta name="description" content="{DESCRIPTION.format(slug)}">{VIEWPORT}'
    if body is None:
        body = f"<h1>{H1.format(slug)}</h1><h2>{H2.format(slug)}</h2>"
    return f"<html><head>{head}</head><body>{body}{'' if thin else FILLER}{_links(links)}</body></html>"


def _head(slug: str, *, title: str | None = None, description: str | None = None, extra: str = "") -> str:
    title = TITLE.format(slug) if title is None else title
    description = DESCRIPTION.format(slug) if description is None else description
    return f'<title>{title}</title><meta name="description" content="{description}">{VIEWPORT}{extra}'


def _no_title(slug: str) -> str:
    return f'<meta name="description" content="{DESCRIPTION.format(slug)}">{VIEWPORT}'


def _no_description(slug: str) -> str:
    return f"<title>{TITLE.format(slug)}</title>{VIEWPORT}"


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


def _canonical(href: str, extra: str = "") -> str:
    return f'<link rel="canonical" href="{href}"{extra}>'


def _robots(content: str) -> str:
    return f'<meta name="robots" content="{content}">'


# `{base}` becomes the polygon's own http://host:port at response time (absolute canonicals).
DIRECTIVE_CANONICAL_TRAPS: dict[str, tuple[dict[str, str], str]] = {
    # Canonicals
    "/c-conflict": ({}, _html("c-conflict", head=_head("c-conflict", extra=_canonical("{base}/c-conflict") + _canonical("{base}/a")))),
    "/c-multiple": ({}, _html("c-multiple", head=_head("c-multiple", extra=_canonical("{base}/c-multiple") * 2))),
    "/c-nonindexable": ({}, _html("c-nonindexable", head=_head("c-nonindexable", extra=_canonical("{base}/r-noindex")))),
    "/c-invalid": ({}, _html("c-invalid", head=_head("c-invalid", extra=_canonical("{base}/c-invalid", ' hreflang="ru"')))),
    "/c-fragment": ({}, _html("c-fragment", head=_head("c-fragment", extra=_canonical("{base}/c-fragment#top")))),
    "/c-outside": ({}, _html("c-outside", body=_canonical("{base}/c-outside") + "<h1>c-outside</h1><h2>c-outside</h2>")),
    "/c-canonicalised": ({}, _html("c-canonicalised", head=_head("c-canonicalised", extra=_canonical("{base}/a")))),
    "/c-missing": ({}, _html("c-missing")),  # the one clean page without a canonical (see NO_CANONICAL)
    "/c-relative": ({}, _html("c-relative", head=_head("c-relative", extra=_canonical("/c-relative")))),
    "/c-header-conflict": (
        {"Link": '<{base}/a>; rel="canonical"'},
        _html("c-header-conflict", head=_head("c-header-conflict", extra=_canonical("{base}/c-header-conflict"))),
    ),
    # Directives
    "/r-outside": ({}, _html("r-outside", body=_robots("index, follow") + "<h1>r-outside</h1><h2>r-outside</h2>")),
    "/r-noimageindex": ({}, _html("r-noimageindex", head=_head("r-noimageindex", extra=_robots("noimageindex")))),
    "/r-noindex": ({}, _html("r-noindex", head=_head("r-noindex", extra=_robots("noindex")))),
    "/r-noindex-header": ({"X-Robots-Tag": "noindex"}, _html("r-noindex-header")),
    "/r-nofollow": ({}, _html("r-nofollow", head=_head("r-nofollow", extra=_robots("nofollow")))),
    "/r-none": ({}, _html("r-none", head=_head("r-none", extra=_robots("none")))),
    "/r-unavailable": ({"X-Robots-Tag": "unavailable_after: 2030-01-01"}, _html("r-unavailable")),
    "/r-nosnippet": ({}, _html("r-nosnippet", head=_head("r-nosnippet", extra=_robots("nosnippet")))),
    "/r-noodp": ({}, _html("r-noodp", head=_head("r-noodp", extra=_robots("noodp")))),
    "/r-noydir": ({}, _html("r-noydir", head=_head("r-noydir", extra=_robots("noydir")))),
    "/r-notranslate": ({}, _html("r-notranslate", head=_head("r-notranslate", extra=_robots("notranslate")))),
}  # fmt: skip
_BODY = "<h1>{h1}</h1><h2>{h2}</h2>"
# readability (Oborneva's Flesch for Russian): long sentences of long words; the filler scores ~75 (easy)
READ_HARD = "Мы долго обсуждали правила работы и решили сменить порядок проверки всех документов. " * 18  # ~41
READ_VERY_HARD = (
    "Высококвалифицированные специалисты исследовательского подразделения систематически анализируют "
    "многочисленные характеристики экспериментальных технологических процессов производства, "
    "обеспечивающих конкурентоспособность отечественной промышленности. "
) * 16
NEAR_TEXT = " ".join(f"слово{i}" + ("." if i % 8 == 7 else "") for i in range(240))  # 240 distinct words
CONTENT_TRAPS: dict[str, str] = {
    "/thin": _html("thin", thin=True),
    "/lorem": _html(
        "lorem", body=f"<h1>{H1.format('lorem')}</h1><h2>{H2.format('lorem')}</h2><p>Lorem ipsum dolor sit amet.</p>"
    ),
    # byte-identical pages; the copy points its canonical at the original, as sites usually do — so the copy is
    # not indexable and, with thresholds.duplicates_indexable_only (default), not a duplicate
    "/dup-1": _html("dup", head=_head("dup", extra=_canonical("{base}/dup-1"))),
    "/dup-2": _html("dup", head=_head("dup", extra=_canonical("{base}/dup-1"))),
    # byte-identical and both indexable: each has its self-canonical in the Link header (see CONTENT_HEADERS)
    "/dup-3": _html("dup-b"),
    "/dup-4": _html("dup-b"),
    "/soft-404": _html("soft-404", head=_head("soft-404", title="Страница не найдена — полигон spider, раздел ошибок")),
    "/read-hard": _html(
        "read-hard",
        thin=True,
        body=_BODY.format(h1=H1.format("read-hard"), h2=H2.format("read-hard")) + "<p>" + READ_HARD + "</p>",
    ),
    "/read-very-hard": _html(
        "read-very-hard",
        thin=True,
        body=_BODY.format(h1=H1.format("read-very-hard"), h2=H2.format("read-very-hard"))
        + "<p>"
        + READ_VERY_HARD
        + "</p>",
    ),
    "/near-1": _html(
        "near-1", thin=True, body=f"<h1>{H1.format('near-1')}</h1><h2>{H2.format('near-1')}</h2><p>{NEAR_TEXT}</p>"
    ),
    "/near-2": _html(
        "near-2",
        thin=True,
        body=f"<h1>{H1.format('near-2')}</h1><h2>{H2.format('near-2')}</h2><p>{NEAR_TEXT.replace('слово7 ', 'иное7 ')}</p>",
    ),
}
CONTENT_HEADERS = {path: {"Link": f'<{{base}}{path}>; rel="canonical"'} for path in ("/dup-3", "/dup-4")}
# collect.near_duplicates on: pages whose texts are ≥ 90 % alike (the polygon's other pages share only the filler)
NEAR_DUPLICATES = {"/near-1", "/near-2", "/dup-3", "/dup-4", "/b", "/b?sort=price"}  # fmt: skip
# `{local}` becomes http://localhost:port — the polygon under another host name, i.e. an external site.
LINK_TRAPS: dict[str, str] = {
    "/l-external": _html("l-external", "{local}/missing", "{local}/error", "https://unreachable.invalid/", "/"),
    "/l-uncrawlable": _html(
        "l-uncrawlable",
        "/",
        body=f"<h1>{H1.format('l-uncrawlable')}</h1><h2>{H2.format('l-uncrawlable')}</h2>"
        '<a href="javascript:void(0)">меню</a><span href="/a">псевдоссылка</span>',
    ),
    "/l-dead-end": _html("l-dead-end", dead_end=True),
    "/l-noindex-hub": _html(
        "l-noindex-hub", "/l-only-from-noindex", head=_head("l-noindex-hub", extra=_robots("noindex"))
    ),
    "/l-only-from-noindex": _html("l-only-from-noindex"),
    "/l-nofollow": _html(
        "l-nofollow",
        "/",
        body=f"<h1>{H1.format('l-nofollow')}</h1><h2>{H2.format('l-nofollow')}</h2>"
        '<a href="/l-nofollow-only" rel="nofollow">только nofollow</a><a href="/l-mixed" rel="nofollow">смешанная</a>',
    ),
    "/l-mixed": _html("l-mixed"),  # also linked (follow) from home
    "/l-many-external": _html("l-many-external", *(f"https://ext-{i}.invalid/" for i in range(11)), "/"),
    "/l-many-internal": _html("l-many-internal", *(["/a"] * 1001)),
    "/deep1": _html("deep1", "/deep2"),
    "/deep2": _html("deep2", "/deep3"),
    "/deep3": _html("deep3", "/deep4"),
    "/deep4": _html("deep4"),
    "/l-no-anchor": _html(
        "l-no-anchor",
        "/",
        body=f"<h1>{H1.format('l-no-anchor')}</h1><h2>{H2.format('l-no-anchor')}</h2>"
        '<a href="/a"></a><a href="/c"><img src="/pic.png"></a>',
    ),
    "/l-vague": _html(
        "l-vague", "/", body=f'<h1>{H1.format("l-vague")}</h1><h2>{H2.format("l-vague")}</h2><a href="/a">Подробнее</a>'
    ),
    "/c-to-unlinked": _html("c-to-unlinked", head=_head("c-to-unlinked", extra=_canonical("{base}/c-unlinked"))),
    "/c-unlinked": _html("c-unlinked"),  # reached only through the canonical above
}
LINKED_FROM_HOME = [
    p for p in LINK_TRAPS if p not in {"/l-only-from-noindex", "/deep2", "/deep3", "/deep4", "/c-unlinked"}
]
# Binary resources: path -> size in bytes (served as image/png etc.; see _handle).
RESOURCES = {
    "/logo.png": 2_000,
    "/pic.png": 2_000,
    "/img/ok.png": 2_000,
    "/img/noalt.png": 2_000,
    "/img/emptyalt.png": 2_000,
    "/img/longalt.png": 2_000,
    "/img/nosize.png": 2_000,
    "/img/big.png": 150_000,  # over thresholds.image_kb (100)
    "/style.css": 500,
    "/app.js": 500,
    "/private/hidden.png": 2_000,  # disallowed by robots.txt: never fetched
    "/big.js": 2_200_000,  # over thresholds.resource_max_mb (2)
}
_IMG = '<img src="{src}" alt="{alt}" width="10" height="10">'
IMAGE_TRAPS: dict[str, str] = {
    "/i-images": _html(
        "i-images",
        "/",
        head=_head("i-images", extra='<link rel="stylesheet" href="/style.css"><script src="/app.js"></script>'),
        body=f"<h1>{H1.format('i-images')}</h1><h2>{H2.format('i-images')}</h2>"
        + _IMG.format(src="/img/ok.png", alt="Нормальная картинка")
        + '<img src="/img/noalt.png" width="10" height="10">'
        + _IMG.format(src="/img/emptyalt.png", alt="")
        + _IMG.format(src="/img/longalt.png", alt="Очень длинное описание картинки " * 5)
        + '<img src="/img/nosize.png" alt="Без размеров">'
        + _IMG.format(src="/img/big.png", alt="Тяжёлая картинка")
        + _IMG.format(src="/img/broken.png", alt="Битая картинка")  # 404: blocked resource
        + _IMG.format(src="/private/hidden.png", alt="Закрытая robots.txt")  # blocked resource
        + _IMG.format(src="{local}/img/gone.png", alt="Чужая пропавшая"),  # external 404
    ),
}
# JS rendering (#15): title, h1 and a link exist only after the script runs. Not linked from the main
# graph — a crawl with rendering starts right at /js-only, so the other traps' expectations stay put.
_JS = (
    "<script>document.title = 'Заголовок из JS';"
    "const h = document.createElement('h1'); h.textContent = 'H1 из JS'; document.body.prepend(h);"
    "const a = document.createElement('a'); a.href = '/js-target'; a.textContent = 'ссылка из JS';"
    "document.body.append(a);</script>"
)
JS_TRAPS: dict[str, str] = {
    "/js-only": f"<html><head></head><body><p>Текст без JS.</p>{_JS}</body></html>",
    "/js-target": _html("js-target", dead_end=True),
}


# JavaScript raw vs rendered (#39): crawled with rendering from /js/ (not linked from the main graph). Each page's
# script changes one thing; the server's HTML is otherwise a clean page.
def _js(slug: str, script: str, *, head: str | None = None, body: str | None = None) -> str:
    return _html(slug, "/js/", head=head, body=(body if body is not None else
                 f"<h1>{H1.format(slug)}</h1><h2>{H2.format(slug)}</h2>") + f"<script>{script}</script>")  # fmt: skip


def _set_meta(name: str, value: str) -> str:
    return f"document.querySelector('meta[name={name}]').setAttribute('content', '{value}');"


JS_WORDS = " ".join(["слово"] * 30)
JS_PAGES: dict[str, str] = {
    "/js/noindex": _js("js-noindex", _set_meta("robots", "index, follow"),
                       head=_head("js-noindex", extra=_robots("noindex"))),
    "/js/nofollow": _js("js-nofollow", _set_meta("robots", "index, follow"),
                        head=_head("js-nofollow", extra=_robots("nofollow"))),
    "/js/canonical-changed": _js("js-canonical-changed",
                                 "document.querySelector('link[rel=canonical]').href = '/js/canonical-target';"),
    "/js/canonical-target": _html("js-canonical-target", "/js/"),
    "/js/canonical-added": _js("js-canonical-added", "const c = document.createElement('link'); "
                               "c.rel = 'canonical'; c.href = location.href; document.head.append(c);"),
    "/js/title-added": _js("js-title-added", f"document.title = '{TITLE.format('js-title-added')}';",
                           head=_no_title("js-title-added")),
    "/js/title-updated": _js("js-title-updated", f"document.title = '{TITLE.format('js-title-updated, новый')}';"),
    "/js/description-added": _js("js-description-added", "const m = document.createElement('meta'); "
                                 f"m.name = 'description'; m.content = '{DESCRIPTION.format('js-description-added')}'; "
                                 "document.head.append(m);", head=_no_description("js-description-added")),
    "/js/description-updated": _js("js-description-updated",
                                   _set_meta("description", DESCRIPTION.format("js-description-updated, новое"))),
    "/js/h1-added": _js("js-h1-added", "const h = document.createElement('h1'); "
                        f"h.textContent = '{H1.format('js-h1-added')}'; document.body.prepend(h);",
                        body=f"<h2>{H2.format('js-h1-added')}</h2>"),
    "/js/h1-updated": _js("js-h1-updated", f"document.querySelector('h1').textContent = '{H1.format('js-h1, новый')}';"),
    "/js/links": _js("js-links", "const a = document.createElement('a'); a.href = '/js/linked'; "
                     "a.textContent = 'ссылка'; document.body.append(a);"),
    "/js/linked": _html("js-linked", "/js/"),
    "/js/content": _js("js-content", f"const p = document.createElement('p'); p.textContent = '{JS_WORDS}'; "
                       "document.body.append(p);"),
    "/js/errors": _js("js-errors", "console.error('polygon: broken widget'); undefinedFunction();"),
    "/js/blocked": _js("js-blocked", "", head=_head("js-blocked", extra='<script src="/private/app.js"></script>')),
    "/js/redirect": _js("js-redirect", "location.replace('/js/landing');"),
    "/js/landing": _html("js-landing", "/js/"),
    # web components and frames: their content counts only when flattened (crawl.render_flatten_*)
    "/js/shadow": _js("js-shadow", "const host = document.getElementById('host'); const root = "
                      "host.attachShadow({mode: 'open'}); root.innerHTML = '<a href=\"/js/shadow-target\">тень</a>';",
                      body=f"<h1>{H1.format('js-shadow')}</h1><h2>{H2.format('js-shadow')}</h2><div id=\"host\"></div>"),
    "/js/shadow-target": _html("js-shadow-target", "/js/"),
    "/js/frame": _html("js-frame", "/js/", body=f"<h1>{H1.format('js-frame')}</h1><h2>{H2.format('js-frame')}</h2>"
                       '<iframe src="/js/framed"></iframe>'),
    "/js/framed": _html("js-framed", "/js/frame-target"),
    "/js/frame-target": _html("js-frame-target", "/js/"),
    # not linked: crawl.render_viewport — the title says how wide the window was
    "/js/viewport": _js("js-viewport", "document.title = 'width ' + window.innerWidth;"),
}  # fmt: skip
JS_LINKED = ("/js/noindex", "/js/nofollow", "/js/canonical-changed", "/js/canonical-added", "/js/title-added",
             "/js/title-updated", "/js/description-added", "/js/description-updated", "/js/h1-added", "/js/h1-updated",
             "/js/links", "/js/content", "/js/errors", "/js/blocked", "/js/redirect", "/js/shadow", "/js/frame")  # fmt: skip
JS_PAGES["/js/"] = _html("js-hub", *JS_LINKED)
JS_NO_CANONICAL = {"/js/canonical-added"}
# the rendered crawl from /js/: issue code -> pages (every JavaScript rule; the old AJAX scheme is in the main graph)
JS_EXPECTED = {
    "js_noindex_only_original": {"/js/noindex"},
    "js_nofollow_only_original": {"/js/nofollow"},
    "js_canonical_mismatch": {"/js/canonical-changed"},
    "js_ajax_scheme_urls": set(),
    "js_ajax_meta_fragment": set(),
    "js_blocked_resources": {"/js/blocked"},
    "js_links": {"/js/links", "/js/shadow", "/js/frame"},
    "js_content": {"/js/content", "/js/frame"},  # the frame's text becomes the page's
    "js_title_only_rendered": {"/js/title-added"},
    "js_title_updated": {"/js/title-updated"},
    "js_description_only_rendered": {"/js/description-added"},
    "js_description_updated": {"/js/description-updated"},
    "js_h1_only_rendered": {"/js/h1-added"},
    "js_h1_updated": {"/js/h1-updated"},
    "js_canonical_only_rendered": {"/js/canonical-added"},
    "js_errors": {"/js/errors"},
    "internal_redirection_javascript": {"/js/redirect"},
}
# the old AJAX crawling scheme (no rendering needed): in the main graph
AJAX_TRAPS: dict[str, str] = {
    "/ajax-hashbang": _html("ajax-hashbang", "/", "/a#!/catalog"),
    "/ajax-fragment": _html("ajax-fragment", head=_head("ajax-fragment", extra='<meta name="fragment" content="!">')),
}

# URL checks (#26): the address itself is the trap. Keys are what a link's href says; ROUTES serves them
# by path (the server sees the decoded path, without the query).
LONG_PATH = "/u/" + "long-" * 20
URL_TRAPS: dict[str, str] = {
    "/u//double": _html("u-double"),
    "/u/with space": _html("u-space"),
    "/u/кириллица": _html("u-cyrillic"),
    "/u/UPPER": _html("u-upper"),
    "/u/shoes/shoes": _html("u-repetitive"),
    "/search?q=test": _html("u-search"),
    "/u/landing?utm_source=news": _html("u-landing"),
    "/u/under_score": _html("u-underscore"),
    LONG_PATH: _html("u-long"),
    # "#top" and "#/route" are not bookmarks; "#exists" names an id of /u/anchors, "#missing" does not
    "/u/bookmarks": _html("u-bookmarks", "/u/anchors#exists", "/u/anchors#missing", "#top", "/u/anchors#/route"),
    "/u/anchors": _html("u-anchors", body=f'<h1>{H1.format("u-anchors")}</h1><h2 id="exists">{H2.format("u-anchors")}</h2>'),
}  # fmt: skip


def _alternates(*pairs: tuple[str, str]) -> str:
    """<link rel="alternate" hreflang> elements: (code, polygon path)."""
    return "".join(f'<link rel="alternate" hreflang="{code}" href="{{base}}{path}">' for code, path in pairs)


def _hl(slug: str, *pairs: tuple[str, str], extra: str = "") -> str:
    return _html(slug, head=_head(slug, extra=_alternates(*pairs) + extra))


# Hreflang (#27): /hl/en and /hl/ru are a clean pair; every other page is one check's trap.
HREFLANG_TRAPS: dict[str, str] = {
    "/hl/en": _hl("hl-en", ("en", "/hl/en"), ("ru", "/hl/ru"), ("x-default", "/hl/en")),
    "/hl/ru": _hl("hl-ru", ("ru", "/hl/ru"), ("en", "/hl/en"), ("x-default", "/hl/en")),
    "/hl/non200": _hl("hl-non200", ("en", "/hl/non200"), ("x-default", "/hl/non200"), ("ru", "/missing")),
    "/hl/noreturn": _hl("hl-noreturn", ("en", "/hl/noreturn"), ("x-default", "/hl/noreturn"), ("ru", "/hl/ru")),
    # fr links back to en with "de", a code en doesn't give itself
    "/hl/incons-en": _hl("hl-incons-en", ("en", "/hl/incons-en"), ("x-default", "/hl/incons-en"),
                         ("fr", "/hl/incons-fr")),
    "/hl/incons-fr": _hl("hl-incons-fr", ("fr", "/hl/incons-fr"), ("x-default", "/hl/incons-en"),
                         ("de", "/hl/incons-en")),
    "/hl/nc-en": _hl("hl-nc-en", ("en", "/hl/nc-en"), ("x-default", "/hl/nc-en"), ("ru", "/c-canonicalised")),
    "/hl/ni-en": _hl("hl-ni-en", ("en", "/hl/ni-en"), ("x-default", "/hl/ni-en"), ("ru", "/r-noindex")),
    "/hl/badcode": _hl("hl-badcode", ("en-UK", "/hl/badcode"), ("x-default", "/hl/badcode")),
    "/hl/multi": _hl("hl-multi", ("en", "/hl/multi"), ("x-default", "/hl/multi"), ("de", "/a"), ("DE", "/b")),
    # canonicalised to /hl/en, but its hreflang names itself
    "/hl/nuc": _hl("hl-nuc", ("en", "/hl/nuc"), ("x-default", "/hl/nuc"), extra=_canonical("{base}/hl/en")),
    "/hl/outside": _html("hl-outside", body=_alternates(("en", "/hl/outside"), ("x-default", "/hl/outside"))
                         + "<h1>hl-outside</h1><h2>hl-outside</h2>"),
    "/hl/unl-en": _hl("hl-unl-en", ("en", "/hl/unl-en"), ("x-default", "/hl/unl-en"), ("fr", "/hl/unl-fr")),
    "/hl/unl-fr": _hl("hl-unl-fr", ("fr", "/hl/unl-fr"), ("en", "/hl/unl-en"), ("x-default", "/hl/unl-en")),
    "/hl/noself": _hl("hl-noself", ("ru", "/hl/ru")),
    "/hl/nox": _hl("hl-nox", ("en", "/hl/nox")),
}  # fmt: skip
HREFLANG_LINKED = [p for p in HREFLANG_TRAPS if p != "/hl/unl-fr"]  # /hl/unl-fr: reached through hreflang only
# the same annotations in the Link header instead of the HTML (clean)
HREFLANG_HEADER = (
    '<{base}/hl/header>; rel="alternate"; hreflang="en", <{base}/hl/header>; rel="alternate"; hreflang="x-default"'
)


def _pg(
    slug: str,
    *anchors: str,
    rel: tuple[tuple[str, str], ...] = (),
    head_extra: str = "",
    title: str | None = None,
    body: str | None = None,
) -> str:
    """A page of a rel next/prev series: `rel` — (next|prev, path) <link> elements, `anchors` — its <a> links."""
    links = "".join(f'<link rel="{r}" href="{{base}}{path}">' for r, path in rel)
    return _html(slug, *anchors, head=_head(slug, title=title, extra=links + head_extra), body=body)


# Pagination (#28): /pg/1–3 is a clean series; the rest are one check's trap each.
_SAME = "Одинаковый заголовок страниц списка pg-dup"
PAGINATION_TRAPS: dict[str, str] = {
    "/pg/1": _pg("pg-1", "/pg/2", rel=(("next", "/pg/2"),)),
    "/pg/2": _pg("pg-2", "/pg/1", "/pg/3", rel=(("prev", "/pg/1"), ("next", "/pg/3"))),
    "/pg/3": _pg("pg-3", "/pg/2", rel=(("prev", "/pg/2"),)),
    "/pg-na/1": _pg("pg-na-1", "/", rel=(("next", "/pg-na/2"),)),  # no <a href="/pg-na/2"> here
    "/pg-na/2": _pg("pg-na-2", "/pg-na/1", rel=(("prev", "/pg-na/1"),)),
    "/pg-bad": _pg("pg-bad", "/missing", rel=(("next", "/missing"),)),
    "/pg-un/1": _pg("pg-un-1", "/", rel=(("next", "/pg-un/2"),)),  # /pg-un/2 is linked from nowhere
    "/pg-un/2": _pg("pg-un-2", "/pg-un/1", rel=(("prev", "/pg-un/1"),)),
    "/pg-multi": _pg("pg-multi", "/a", "/b", rel=(("next", "/a"), ("next", "/b"))),
    "/pg-loop/1": _pg("pg-loop-1", "/pg-loop/2", rel=(("next", "/pg-loop/2"), ("prev", "/pg-loop/2"))),
    "/pg-loop/2": _pg("pg-loop-2", "/pg-loop/1", rel=(("next", "/pg-loop/1"), ("prev", "/pg-loop/1"))),
    "/pg-seq/1": _pg("pg-seq-1", "/pg-seq/2", rel=(("next", "/pg-seq/2"),)),
    "/pg-seq/2": _pg("pg-seq-2", "/pg/1", rel=(("prev", "/pg/1"),)),  # prev should be /pg-seq/1
    "/pg-ni/1": _pg("pg-ni-1", "/pg-ni/2", rel=(("next", "/pg-ni/2"),)),
    "/pg-ni/2": _pg("pg-ni-2", "/pg-ni/1", rel=(("prev", "/pg-ni/1"),), head_extra=_robots("noindex")),
    # page 2 repeats page 1's title and headings: not a duplicate while ignore_paginated_duplicates is on
    "/pg-dup/1": _pg("pg-dup", "/pg-dup/2", rel=(("next", "/pg-dup/2"),), title=_SAME),
    "/pg-dup/2": _pg("pg-dup", "/pg-dup/1", rel=(("prev", "/pg-dup/1"),), title=_SAME),
}  # fmt: skip
PAGINATION_LINKED = [p for p in PAGINATION_TRAPS if p != "/pg-un/2"]

# Security (#29). Every response carries sound security headers (SECURE_HEADERS); a trap drops one ("" value).
SECURE_HEADERS = {
    "Content-Security-Policy": "default-src 'self' 'unsafe-inline'",  # inline: the JS rendering traps
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}
HSTS = {"Strict-Transport-Security": "max-age=31536000"}  # HTTPS responses only
SECURITY_TRAPS: dict[str, tuple[dict[str, str], str]] = {
    "/s-form": ({}, _html("s-form", body=_BODY.format(h1=H1.format("s-form"), h2=H2.format("s-form"))
                          + '<form action="/s-form-submit" method="post"><input name="q"></form>')),
    "/s-blank": ({}, _html("s-blank", "/", body=_BODY.format(h1=H1.format("s-blank"), h2=H2.format("s-blank"))
                           + '<a href="{local}/a" target="_blank">чужой сайт</a>'
                           + '<a href="{local}/b" target="_blank" rel="noopener">безопасно</a>')),
    "/s-protocol": ({}, _html("s-protocol", body=_BODY.format(h1=H1.format("s-protocol"), h2=H2.format("s-protocol"))
                              + '<img src="//{localhost}/logo.png" alt="Логотип" width="10" height="10">')),
    "/s-no-csp": ({"Content-Security-Policy": ""}, _html("s-no-csp")),
    "/s-no-xcto": ({"X-Content-Type-Options": ""}, _html("s-no-xcto")),
    "/s-no-xfo": ({"X-Frame-Options": "ALLOW-FROM https://x.example"}, _html("s-no-xfo")),
    "/s-bad-referrer": ({"Referrer-Policy": "unsafe-url"}, _html("s-bad-referrer")),
    "/s-badtype": ({"Content-Type": "image/png"}, _html("s-badtype")),  # an HTML page served as an image
}  # fmt: skip
# The HTTPS polygon (serve(https=True)): `{insecure}` is the same host over plain http://.
HTTPS_ROUTES: dict[str, tuple[int, dict[str, str], str]] = {
    "/": (200, {}, _html("https-home", "/mixed", "/form-insecure", "/nohsts", "/plain", "{insecure}/plain")),
    "/mixed": (200, {}, _html("mixed", body=_BODY.format(h1="mixed", h2="mixed")
                              + '<img src="{insecure}/img.png" alt="По HTTP" width="10" height="10">')),
    "/form-insecure": (200, {}, _html("form-insecure", body=_BODY.format(h1="form", h2="form")
                                      + '<form action="{insecure}/submit" method="post"></form>')),
    "/nohsts": (200, {"Strict-Transport-Security": ""}, _html("nohsts")),
    "/plain": (200, {}, _html("plain")),
}  # fmt: skip
# security rules on the HTTPS polygon crawl; "INSECURE" stands for http://host:port (the HTTPS polygon's own port)
HTTPS_EXPECTED = {
    "security_http_urls": {"INSECURE/plain", "INSECURE/img.png"},
    "security_mixed_content": {"/mixed"},
    "security_form_url_insecure": {"/form-insecure"},
    "security_form_on_http": set(),
    "security_missing_hsts": {"/nohsts"},
}


def _ld(data: dict) -> str:
    import json as _json

    return f'<script type="application/ld+json">{_json.dumps(data, ensure_ascii=False)}</script>'


_OFFER = {
    "@type": "Offer",
    "price": "10.00",
    "priceCurrency": "RUB",
    "availability": "https://schema.org/InStock",
    "url": "{base}/sd/ok",
}
_PRODUCT = {"@context": "https://schema.org", "@type": "Product", "name": "Товар", "image": "{base}/logo.png",
            "description": "Описание товара", "sku": "A-1", "brand": {"@type": "Brand", "name": "Марка"},
            "offers": _OFFER,
            "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.5", "ratingCount": "10",
                                "bestRating": "5", "worstRating": "1"},
            "review": {"@type": "Review", "author": {"@type": "Person", "name": "Иван"}, "datePublished": "2026-01-01",
                       "reviewRating": {"@type": "Rating", "ratingValue": "5"}}}  # fmt: skip
_MICRO_ORG = ('<div itemscope itemtype="https://schema.org/Organization"><span itemprop="name">Полигон</span>'
              '<link itemprop="url" href="{base}/"><link itemprop="logo" href="{base}/logo.png"></div>')  # fmt: skip
# Structured data (#31) under /sd/: a crawl with collect.structured_data starts at /sd/ and stays in the folder.
STRUCTURED_TRAPS: dict[str, str] = {
    "/sd/": _html("sd", *(f"/sd/{name}" for name in ("ok", "invalid", "rich-error", "parse", "warning", "rich-warning",
                                                      "rdfa"))),
    "/sd/ok": _html("sd-ok", head=_head("sd-ok", extra=_ld(_PRODUCT))),
    "/sd/invalid": _html("sd-invalid", head=_head("sd-invalid", extra=_ld(
        {"@context": "https://schema.org", "@type": "Organization", "name": "Фирма", "url": "{base}/", "logo": "{base}/logo.png",
         "colour": "красный", "department": {"@type": "Departmentt", "name": "Отдел"}}))),
    "/sd/rich-error": _html("sd-rich-error", head=_head("sd-rich-error", extra=_ld(
        {"@context": "https://schema.org", "@type": "Event", "name": "Событие"}))),
    "/sd/parse": _html("sd-parse", head=_head("sd-parse", extra='<script type="application/ld+json">{"@type": </script>'),
                       body=_BODY.format(h1=H1.format("sd-parse"), h2=H2.format("sd-parse")) + _MICRO_ORG),
    # the retired data-vocabulary.org and a superseded Schema.org property
    "/sd/warning": _html("sd-warning", head=_head("sd-warning", extra=_ld(
        {"@context": "https://schema.org", "@type": "Organization", "name": "Фирма", "url": "{base}/",
         "logo": "{base}/logo.png", "branchOf": {"@type": "Organization", "name": "Головная", "url": "{base}/",
                                                 "logo": "{base}/logo.png"}})),
        body=_BODY.format(h1=H1.format("sd-warning"), h2=H2.format("sd-warning"))
        + '<div itemscope itemtype="http://data-vocabulary.org/Breadcrumb"><span itemprop="title">Главная</span></div>'),
    "/sd/rich-warning": _html("sd-rich-warning", head=_head("sd-rich-warning", extra=_ld(
        {"@context": "https://schema.org", "@type": "Product", "name": "Товар", "offers": _OFFER}))),
    "/sd/rdfa": _html("sd-rdfa", body=_BODY.format(h1=H1.format("sd-rdfa"), h2=H2.format("sd-rdfa"))
                      + '<div vocab="https://schema.org/" typeof="Organization"><span property="name">Полигон</span>'
                      '<a property="url" href="{base}/">сайт</a><img property="logo" src="{base}/logo.png" alt="Логотип" '
                      'width="10" height="10"></div>'),
}  # fmt: skip
# structured data rules on a crawl of /sd/ with every format on
STRUCTURED_EXPECTED = {
    "structured_data_validation_errors": {"/sd/invalid"},
    "structured_data_rich_result_errors": {"/sd/rich-error"},
    "structured_data_parse_errors": {"/sd/parse"},
    "structured_data_missing": {"/sd/"},
    "structured_data_validation_warnings": {"/sd/warning"},
    "structured_data_rich_result_warnings": {"/sd/rich-error", "/sd/rich-warning"},
}


def _urlset(*paths: str, alternates: dict[str, tuple[str, str]] | None = None) -> str:
    alternates = alternates or {}
    urls = "".join(
        f"<url><loc>{{base}}{path}</loc>"
        + (f'<xhtml:link rel="alternate" hreflang="{alternates[path][0]}" href="{{base}}{alternates[path][1]}"/>'
           if path in alternates else "")
        + "</url>"
        for path in paths
    )  # fmt: skip
    return ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
            f' xmlns:xhtml="http://www.w3.org/1999/xhtml">{urls}</urlset>')  # fmt: skip


# Sitemaps (#32) under /sm/, linked from nowhere: a crawl with sitemaps.crawl starts at /sm/ and stays in the
# folder. robots.txt names the index; pages.xml has 5 URLs (the big one for a small thresholds.sitemap_max_urls).
SITEMAP_FILES: dict[str, str] = {
    "/sm/sitemap.xml": '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    + "".join(f"<sitemap><loc>{{base}}/sm/{name}.xml</loc></sitemap>" for name in ("pages", "more", "gone"))
    + "</sitemapindex>",
    "/sm/pages.xml": _urlset(
        "/sm/", "/sm/a", "/sm/orphan", "/sm/noindex", "/sm/twice", alternates={"/sm/a": ("ru", "/sm/a")}
    ),
    "/sm/more.xml": _urlset("/sm/twice"),
}
SITEMAP_TRAPS: dict[str, str] = {
    "/sm/": _html("sm", "/sm/a", "/sm/b", "/sm/noindex", "/sm/twice"),
    "/sm/a": _html("sm-a", "/sm/"),
    "/sm/b": _html("sm-b", "/sm/"),  # linked, not in any sitemap
    "/sm/orphan": _html("sm-orphan", "/sm/"),  # in the sitemap, linked from nowhere
    "/sm/noindex": _html("sm-noindex", "/sm/", head=_head("sm-noindex", extra=_robots("noindex"))),
    "/sm/twice": _html("sm-twice", "/sm/"),  # in both sitemap files
}
# sitemap rules on a crawl of /sm/ with sitemaps.crawl; the size / count ones with small thresholds (see the test)
SITEMAP_EXPECTED = {
    "sitemaps_over_max_urls": {"/sm/pages.xml"},
    "sitemaps_over_max_mb": {"/sm/pages.xml"},
    "sitemaps_urls_not_in_sitemap": {"/sm/b"},
    "sitemaps_orphan_urls": {"/sm/orphan"},
    "sitemaps_non_indexable": {"/sm/noindex"},
    "sitemaps_multiple": {"/sm/twice"},
}


def _page(
    slug: str,
    before_head: str = "",
    head_extra: str = "",
    after_head: str = "",
    body_open: str = "<body>",
    body_close: str = "</body>",
    html_open: str = "<html>",
) -> str:
    """A clean page whose skeleton (the tags around head and body) a trap can bend."""
    head = f"<head>{_head(slug)}{head_extra}</head>" if before_head != "NO-HEAD" else _head(slug)
    return (
        f"{html_open}{'' if before_head == 'NO-HEAD' else before_head}{head}{after_head}{body_open}"
        f'<h1>{H1.format(slug)}</h1><h2>{H2.format(slug)}</h2>{FILLER}<a href="/">/</a>{body_close}</html>'
    )


# HTML validation (#34): the source's skeleton, which an HTML5 parser would silently repair.
BIG_COMMENT = "<!--" + "x" * 2_200_000 + "-->"  # the document over 2 MB without 2 MB of text to read
VALIDATION_TRAPS: dict[str, str] = {
    "/v-no-head": _page("v-no-head", before_head="NO-HEAD").replace("<html>", '<html><link rel="canonical" href="{base}/v-no-head">', 1),
    "/v-two-heads": _page("v-two-heads", after_head="<head></head>"),
    "/v-no-body": _page("v-no-body", body_open="", body_close=""),
    "/v-two-bodies": _page("v-two-bodies", body_close="</body><body></body>"),
    "/v-big": _page("v-big", head_extra='<script src="/big.js"></script>', body_close=BIG_COMMENT + "</body>"),
    "/v-invalid-head": _page("v-invalid-head", head_extra='<img src="/logo.png" alt="Логотип" width="10" height="10">'),
    "/v-before-html": "<div>баннер</div>" + _page("v-before-html"),
    "/v-head-not-first": _page("v-head-not-first", before_head='<meta charset="utf-8">'),
    # Mobile
    "/m-no-viewport": _html("m-no-viewport", head=_head("m-no-viewport").replace(VIEWPORT, "")),
    "/m-plugin": _html("m-plugin", body=f"<h1>{H1.format('m-plugin')}</h1><h2>{H2.format('m-plugin')}</h2>"
                       '<object type="application/x-shockwave-flash" data="/movie.swf"></object>'),
    "/m-alternate": _html("m-alternate", head=_head("m-alternate", extra='<link rel="alternate" '
                          'media="only screen and (max-width: 640px)" href="{base}/m/page">')),
    "/m/page": _html("m-page"),  # the "mobile site", found through the alternate link only
}  # fmt: skip

# Crawl settings (#35). Linked from home: /l-invalid (a link with no host, dropped unless crawl.crawl_invalid_links)
# and /r-noindex-thin (an on-page issue on a non-indexable page: thresholds.issues_indexable_only). The rest are
# crawled on their own by the settings tests.
SETTINGS_TRAPS: dict[str, tuple[int, dict[str, str], str]] = {
    "/l-invalid": (200, {}, _html("l-invalid", "/", body=f"<h1>{H1.format('l-invalid')}</h1><h2>{H2.format('l-invalid')}</h2>"
                                  '<a href="https:///no-host">без хоста</a>')),
    "/r-noindex-thin": (200, {}, _html("r-noindex-thin", thin=True, head=_head("r-noindex-thin", extra=_robots("noindex")))),
    "/cookie-set": (200, {"Set-Cookie": "polygon=1; Path=/"}, _html("cookie-set", "/cookie-check")),
    "/cookie-check": (200, {}, _html("cookie-check", dead_end=True)),
    "/flaky": (200, {}, _html("flaky", dead_end=True)),  # 503 for the first FLAKY_FAILS requests (see _handle)
    "/members/": (200, {}, _html("members", dead_end=True)),  # 401 without Authorization: Basic (see _handle)
    "/self-refresh": (200, {}, _html("self-refresh", dead_end=True,
                                     head=_head("self-refresh", extra='<meta http-equiv="refresh" content="30; url={base}/self-refresh">'))),
}  # fmt: skip
# Custom Search / Extraction and link positions (#36): a page with landmarks, a price and a counter snippet.
CUSTOM_PAGE = (
    '<html><head><title>{t}</title><meta name="description" content="{d}"><meta name="author" content="Редакция">'
    '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-X"></script></head><body>'
    '<header class="site-header"><a href="/a">Главная раздела</a></header>'
    '<nav class="main-menu"><ul><li><a href="/b">Каталог</a></li><li><a href="/c">Доставка</a></li></ul></nav>'
    '<main><h1>Товар дня</h1><h2>Цены</h2><p class="price">1 990 ₽</p><p class="price">2 490 ₽</p>'
    '<p>Акция! Артикул SKU-12345. Акция до конца недели.</p><a href="/shop/">В магазин</a></main>'
    '<aside class="sidebar"><a href="/deep1">Похожее</a></aside>'
    '<footer><a href="/">Контакты</a></footer></body></html>'
).format(t=TITLE.format("custom"), d=DESCRIPTION.format("custom"))
SETTINGS_TRAPS["/cx"] = (200, {}, CUSTOM_PAGE)
# Meta keywords (#38), crawled as a list: the same keywords twice, two tags on one page
_KW = '<meta name="keywords" content="{}">'
SETTINGS_TRAPS["/mk-1"] = (200, {}, _html("mk-1", head=_head("mk-1", extra=_KW.format("диван, кресло"))))
SETTINGS_TRAPS["/mk-2"] = (200, {}, _html("mk-2", head=_head("mk-2", extra=_KW.format("диван, кресло"))))
SETTINGS_TRAPS["/mk-3"] = (200, {}, _html("mk-3", head=_head("mk-3", extra=_KW.format("стол") + _KW.format("стул"))))
FLAKY_FAILS = 2
FLAKY_SEEN: dict[str, int] = {}
BASIC_AUTH = "Basic " + __import__("base64").b64encode(b"stage:pa55").decode()

NO_CANONICAL = {"/c-missing", "/dup-3", "/dup-4", *JS_NO_CANONICAL}  # /dup-3, /dup-4: canonical in the Link header

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
            *DIRECTIVE_CANONICAL_TRAPS,
            *CONTENT_TRAPS,
            "/g-blocked",
            "/shop/",
            *LINKED_FROM_HOME,
            "/l-mixed",
            *IMAGE_TRAPS,
            *URL_TRAPS,
            *HREFLANG_LINKED,
            "/hl/header",
            *PAGINATION_LINKED,
            *(p for p in VALIDATION_TRAPS if p != "/m/page"),
            "/l-invalid",
            "/r-noindex-thin",
            *SECURITY_TRAPS,
            "/sd/",
            *AJAX_TRAPS,
        ),
    ),
    "/a": (200, {}, _html("a", "/c")),
    "/b": (200, {}, _html("b", "/")),
    "/c": (200, {}, _html("c")),
    "/old": (301, {"Location": "/a"}, ""),
    "/missing": (404, {}, "<html><body>Не найдено</body></html>"),
    # --- Response Codes traps ---
    # Googlebot has its own group: /g-blocked is closed to it only (crawl.user_agent / robots_user_agent)
    "/robots.txt": (
        200,
        {"Content-Type": "text/plain"},
        "User-agent: *\nDisallow: /private/\n\nUser-agent: Googlebot\nDisallow: /private/\nDisallow: /g-blocked\n"
        "\nSitemap: {base}/sm/sitemap.xml\n",
    ),
    "/g-blocked": (200, {}, _html("g-blocked")),
    "/shop/": (200, {}, _html("shop", "/shop/item", "/a")),  # the start folder for stay_in_start_folder
    "/shop/item": (200, {}, _html("shop-item")),
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
    **{path: (200, headers, html) for path, (headers, html) in DIRECTIVE_CANONICAL_TRAPS.items()},
    **{path: (200, CONTENT_HEADERS.get(path, {}), html) for path, html in CONTENT_TRAPS.items()},
    **{path: (200, {}, html) for path, html in LINK_TRAPS.items()},
    **{path: (200, {}, html) for path, html in IMAGE_TRAPS.items()},
    **{path: (200, {}, html) for path, html in JS_TRAPS.items()},
    **{path: (200, {}, html) for path, html in JS_PAGES.items()},
    **{path: (200, {}, html) for path, html in AJAX_TRAPS.items()},
    "/private/app.js": (200, {"Content-Type": "text/javascript"}, "document.title = 'из закрытого скрипта';"),
    **{path.partition("?")[0]: (200, {}, html) for path, html in URL_TRAPS.items()},
    **{path: (200, {}, html) for path, html in HREFLANG_TRAPS.items()},
    "/hl/header": (200, {"Link": HREFLANG_HEADER}, _html("hl-header")),
    **{path: (200, {}, html) for path, html in PAGINATION_TRAPS.items()},
    **{path: (200, headers, html) for path, (headers, html) in SECURITY_TRAPS.items()},
    **{path: (200, {}, html) for path, html in STRUCTURED_TRAPS.items()},
    **{path: (200, {}, html) for path, html in VALIDATION_TRAPS.items()},
    **SETTINGS_TRAPS,
    **{path: (200, {"Content-Type": "application/xml"}, xml) for path, xml in SITEMAP_FILES.items()},
    **{path: (200, {}, html) for path, html in SITEMAP_TRAPS.items()},
    # not linked: a crawl or fetch starts right at it (response details, #25)
    "/dated": (200, {"Last-Modified": "Wed, 01 Jan 2025 10:00:00 GMT"}, _html("dated", dead_end=True)),
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
    *DIRECTIVE_CANONICAL_TRAPS,
    *CONTENT_TRAPS,
    "/g-blocked",
    "/shop/",
    "/shop/item",
    *LINK_TRAPS,
    *IMAGE_TRAPS,
    *RESOURCES,
    "/img/broken.png",
    *URL_TRAPS,
    *HREFLANG_TRAPS,
    "/hl/header",
    *PAGINATION_TRAPS,
    *SECURITY_TRAPS,
    *STRUCTURED_TRAPS,
    *VALIDATION_TRAPS,
    "/l-invalid",
    "/r-noindex-thin",
    *AJAX_TRAPS,
}

# Other sites' URLs a full crawl checks (not crawls); "LOCAL" stands for http://localhost:port.
EXTERNAL = {
    "https://external.example/",
    "https://unreachable.invalid/",
    *(f"https://ext-{i}.invalid/" for i in range(11)),
    "LOCAL/missing",
    "LOCAL/error",
    "LOCAL/img/gone.png",
    "LOCAL/a",  # the target=_blank trap's links
    "LOCAL/b",
    "LOCAL/logo.png",  # the protocol-relative image
}

DUPLICATES = {"/b", "/b?sort=price"}
DUPLICATES_B = DUPLICATES | {"/dup-3", "/dup-4"}  # the same title / description / headings too

# issue code -> polygon paths the rule must report (and nothing else).
EXPECTED_ISSUES = {
    # Response Codes
    "internal_no_response": {"/reset"},
    "internal_client_error": {"/missing", "/img/broken.png"},
    "internal_server_error": {"/error"},
    "internal_redirect_loop": {"/loop1", "/loop2"},
    "internal_blocked_by_robots": {"/private/secret", "/private/hidden.png"},
    "internal_redirect_chain": {"/chain1"},
    "internal_redirection_3xx": {"/old", "/chain1", "/chain2", "/loop1", "/loop2", "/to-missing"},
    "internal_redirection_meta_refresh": {"/meta-refresh"},
    "internal_redirection_http_refresh": {"/http-refresh"},
    # Page Titles
    "page_title_missing": {"/t-missing"},
    "page_title_multiple": {"/t-multiple"},
    "page_title_outside_head": {
        "/t-outside",
        "/v-before-html",
    },  # a <div> before <html>: the parser puts the head into <body>
    "page_title_duplicate": DUPLICATES_B,
    "page_title_over_max": {"/t-long"},
    "page_title_below_min": {"/t-short"},
    "page_title_same_as_h1": {"/t-same-h1"},
    "page_title_over_px": {"/t-long"},
    "page_title_below_px": {"/t-short"},
    # Meta Description
    "meta_description_multiple": {"/d-multiple"},
    "meta_description_outside_head": {
        "/d-outside",
        "/v-before-html",
    },  # a <div> before <html>: the parser puts the head into <body>
    "meta_description_missing": {"/d-missing"},
    "meta_description_duplicate": DUPLICATES_B,
    "meta_description_over_max": {"/d-long"},
    "meta_description_below_min": {"/d-short"},
    "meta_description_over_px": {"/d-long"},
    "meta_description_below_px": {"/d-short"},
    # H1
    "h1_missing": {"/h1-missing"},
    "h1_multiple": {"/h1-multiple"},
    "h1_alt_text": {"/h1-alt"},
    "h1_non_sequential": {"/h1-nonseq"},
    "h1_duplicate": DUPLICATES_B,
    "h1_over_max": {"/h1-long"},
    # H2
    "h2_missing": {"/h2-missing"},
    "h2_multiple": {"/h2-multiple"},
    "h2_non_sequential": {"/h2-nonseq", "/h1-missing"},
    "h2_duplicate": DUPLICATES_B,
    "h2_over_max": {"/h2-long"},
    # Canonicals
    "canonical_multiple_conflicting": {"/c-conflict", "/c-header-conflict"},
    "canonical_non_indexable": {"/c-nonindexable"},
    "canonical_invalid_attribute": {"/c-invalid"},
    "canonical_fragment": {"/c-fragment"},
    "canonical_outside_head": {
        "/c-outside",
        "/v-before-html",
    },  # a <div> before <html>: the parser puts the head into <body>
    "canonical_canonicalised": {
        "/c-canonicalised",
        "/c-nonindexable",
        "/c-header-conflict",
        "/dup-2",
        "/c-to-unlinked",
        "/hl/nuc",
    },
    "canonical_missing": {"/c-missing"},
    "canonical_multiple": {"/c-conflict", "/c-multiple", "/c-header-conflict"},
    "canonical_relative": {"/c-relative"},
    # Directives
    "directives_outside_head": {"/r-outside"},
    "directives_noimageindex": {"/r-noimageindex"},
    "directives_noindex": {"/r-noindex", "/r-noindex-header", "/l-noindex-hub", "/pg-ni/2", "/r-noindex-thin"},
    "directives_nofollow": {"/r-nofollow"},
    "directives_none": {"/r-none"},
    "directives_unavailable_after": {"/r-unavailable"},
    "directives_nosnippet": {"/r-nosnippet"},
    "directives_noodp": {"/r-noodp"},
    "directives_noydir": {"/r-noydir"},
    "directives_notranslate": {"/r-notranslate"},
    # Content
    "content_exact_duplicates": {"/dup-3", "/dup-4"},
    "content_soft_404": {"/soft-404"},
    "content_near_duplicates": set(),  # collect.near_duplicates is off in this crawl: see NEAR_DUPLICATES
    "content_readability_difficult": {"/read-hard"},
    "content_readability_very_difficult": {"/read-very-hard"},
    "content_lorem_ipsum": {"/lorem"},
    "content_low_content": {"/thin", "/r-noindex-thin"},  # the noindex one: gone with issues_indexable_only
    # Links
    "links_outlinks_to_localhost": {"/l-external", "/s-blank"},  # /s-blank: its "other site" is the localhost alias
    "links_uncrawlable_outlinks": {"/l-uncrawlable"},
    "links_no_internal_outlinks": {"/l-dead-end"},
    "links_non_indexable_inlinks_only": {"/l-only-from-noindex"},
    "links_internal_nofollow_outlinks": {"/l-nofollow"},
    "links_high_external_outlinks": {"/l-many-external"},
    "links_high_internal_outlinks": {"/l-many-internal"},
    "links_follow_and_nofollow_inlinks": {"/l-mixed"},
    "links_nofollow_inlinks_only": {"/l-nofollow-only"},
    "links_high_crawl_depth": {"/deep4"},
    "links_no_anchor_text": {"/l-no-anchor"},
    "links_non_descriptive_anchor": {"/l-vague"},
    "canonical_unlinked": {"/c-unlinked"},
    # external URLs
    "external_no_response": {u for u in EXTERNAL if not u.startswith("LOCAL")},
    "external_client_error": {"LOCAL/missing", "LOCAL/img/gone.png"},
    "external_server_error": {"LOCAL/error"},
    # Images (reported by image URL) and resources
    "images_missing_alt_text": {"/img/emptyalt.png"},
    "images_missing_alt_attribute": {"/img/noalt.png", "/pic.png"},  # /pic.png: the no-anchor trap's image
    "images_over_max_kb": {"/img/big.png"},
    "images_alt_over_max": {"/img/longalt.png"},
    "images_missing_size": {"/img/nosize.png", "/logo.png", "/pic.png"},  # the h1-alt and no-anchor traps too
    "internal_blocked_resource": {"/img/broken.png", "/private/hidden.png"},
    "external_blocked_resource": {"LOCAL/img/gone.png"},
    # URL
    "url_multiple_slashes": {"/u//double"},
    "url_contains_space": {"/u/with space"},
    "url_broken_bookmark": {"/u/anchors", "/a"},  # /a: home links to /a#reviews, and /a has no such id
    "url_non_ascii": {"/u/кириллица"},
    "url_uppercase": {"/u/UPPER"},
    "url_repetitive_path": {"/u/shoes/shoes"},
    "url_internal_search": {"/search?q=test"},
    "url_parameters": {"/b?sort=price", "/search?q=test", "/u/landing?utm_source=news"},
    "url_ga_tracking": {"/u/landing?utm_source=news"},
    "url_underscores": {"/u/under_score"},
    "url_over_max": {LONG_PATH},
    # Hreflang
    "hreflang_non_200": {"/hl/non200"},
    "hreflang_missing_return": {"/hl/noreturn", "/hl/nc-en", "/hl/ni-en", "/hl/multi", "/hl/noself"},
    "hreflang_inconsistent": {"/hl/incons-en"},
    "hreflang_non_canonical_return": {"/hl/nc-en"},
    "hreflang_noindex_return": {"/hl/ni-en"},
    "hreflang_incorrect_codes": {"/hl/badcode"},
    "hreflang_multiple_entries": {"/hl/multi"},
    "hreflang_not_using_canonical": {"/hl/nuc"},
    "hreflang_outside_head": {"/hl/outside"},
    "hreflang_unlinked": {"/hl/unl-fr"},
    "hreflang_missing_self_reference": {"/hl/noself"},
    "hreflang_missing_x_default": {"/hl/noself", "/hl/nox"},
    # Pagination
    "pagination_not_in_anchor": {"/pg-na/1", "/pg-un/1"},
    "pagination_non_200": {"/pg-bad"},
    "pagination_unlinked": {"/pg-un/2"},
    "pagination_multiple": {"/pg-multi"},
    "pagination_loop": {"/pg-loop/1", "/pg-loop/2"},
    "pagination_sequence_error": {"/pg-multi", "/pg-seq/1", "/pg-seq/2"},
    "pagination_non_indexable": {"/pg-ni/2"},
    # Security (the HTTP polygon: every URL is plain HTTP; HTTPS-only checks — HTTPS_EXPECTED)
    "security_http_urls": set(REACHABLE),
    "security_mixed_content": set(),
    "security_form_url_insecure": set(),
    "security_form_on_http": {"/s-form"},
    "security_missing_hsts": set(),
    "security_unsafe_cross_origin": {"/s-blank"},
    "security_protocol_relative": {"/s-protocol"},
    "security_missing_csp": {"/s-no-csp"},
    "security_missing_x_content_type_options": {"/s-no-xcto"},
    "security_missing_x_frame_options": {"/s-no-xfo"},
    "security_missing_referrer_policy": {"/s-bad-referrer"},
    "security_bad_content_type": {"/s-badtype"},
    # Structured Data: collect.structured_data is off in this crawl — see STRUCTURED_EXPECTED
    **{code: set() for code in STRUCTURED_EXPECTED},
    # Sitemaps: sitemaps.crawl is off in this crawl — see SITEMAP_EXPECTED
    **{code: set() for code in SITEMAP_EXPECTED},
    # Validation
    "validation_missing_head": {"/v-no-head"},
    "validation_multiple_head": {"/v-two-heads"},
    "validation_missing_body": {"/v-no-body"},
    "validation_multiple_body": {"/v-two-bodies"},
    "validation_document_over_max": {"/v-big"},
    "validation_resource_over_max": {"/big.js"},
    "validation_invalid_head_elements": {"/v-invalid-head"},
    "validation_body_before_html": {"/v-before-html"},
    "validation_head_not_first": {"/v-head-not-first"},
    # Mobile
    "mobile_viewport_not_set": {"/m-no-viewport"},
    "mobile_unsupported_plugins": {"/m-plugin"},
    "mobile_alternate_link": {"/m-alternate"},
    # JavaScript: this crawl isn't rendered — see JS_EXPECTED; the old AJAX scheme needs no browser
    **{code: set() for code in JS_EXPECTED},
    "js_ajax_scheme_urls": {"/ajax-hashbang"},
    "js_ajax_meta_fragment": {"/ajax-fragment"},
}

# A test may change the site between two crawls (compare, re-spider): path -> route, consulted first.
OVERRIDES: dict[str, tuple[int, dict[str, str], str]] = {}
HTTPS_CA: bytes = b""  # the running HTTPS polygon's root certificate (PEM)
SEEN_USER_AGENTS: set[str] = set()  # what reached the server — proves crawl.user_agent is sent
SEEN_HEADERS: list[dict[str, str]] = []  # every request's headers, lower-case names — proves crawl.headers are sent
SLOW_S = 3.0  # "/slow" (linked from nowhere) answers after this long: a timeout trap


async def _handle(request: web.Request) -> web.StreamResponse:
    SEEN_USER_AGENTS.add(request.headers.get("User-Agent", ""))
    SEEN_HEADERS.append({k.lower(): v for k, v in request.headers.items()})
    if request.path == "/slow":
        await asyncio.sleep(SLOW_S)
    if request.path in RESOURCES:
        kind = {".css": "text/css", ".js": "text/javascript"}.get(PurePosixPath(request.path).suffix, "image/png")
        return web.Response(body=b"\0" * RESOURCES[request.path], content_type=kind)
    if request.path == "/reset":  # no response at all: the client sees a dropped connection
        assert request.transport is not None
        request.transport.abort()
        return web.Response()
    if request.path == "/flaky":
        FLAKY_SEEN[request.host] = FLAKY_SEEN.get(request.host, 0) + 1
        if FLAKY_SEEN[request.host] <= FLAKY_FAILS:
            return web.Response(status=503, text="later")
    if request.path.startswith("/members/") and request.headers.get("Authorization") != BASIC_AUTH:
        return web.Response(status=401, headers={"WWW-Authenticate": 'Basic realm="polygon"'}, text="login")
    routes = HTTPS_ROUTES if request.secure else ROUTES
    status, headers, body = OVERRIDES.get(request.path) or routes.get(
        request.path, (404, {}, "<html><body>Не найдено</body></html>")
    )
    port = request.host.rsplit(":", 1)[1]
    base = f"{request.scheme}://{request.host}"
    fill = {"{base}": base, "{localhost}": f"localhost:{port}", "{local}": f"http://localhost:{port}",
            "{insecure}": f"http://{request.host}"}  # fmt: skip
    if status == 200 and "<head>" in body and 'rel="canonical"' not in body and request.path not in NO_CANONICAL:
        # clean pages: self, as the page's link spelled it (decoded path — a space, not %20)
        self_url = base + request.path + (f"?{request.query_string}" if request.query_string else "")
        body = body.replace("<head>", f"<head>{_canonical(self_url)}", 1)
    for token, value in fill.items():
        body = body.replace(token, value)
    defaults = {"Content-Type": "text/html; charset=utf-8", **SECURE_HEADERS, **(HSTS if request.secure else {})}
    merged = defaults | {k: v.replace("{base}", base) for k, v in headers.items()}
    return web.Response(status=status, headers={k: v for k, v in merged.items() if v}, text=body)


@contextmanager
def serve(*, https: bool = False) -> Iterator[str]:
    """Run the polygon on a free local port; yields its base URL (no trailing slash).

    `https` — the HTTPS polygon (HTTPS_ROUTES) with a throwaway self-signed certificate: crawl it with
    `crawl.verify_tls = false`.
    """
    loop = asyncio.new_event_loop()
    app = web.Application()
    app.router.add_get("/{tail:.*}", _handle)
    runner = web.AppRunner(app, access_log=None)
    loop.run_until_complete(runner.setup())
    context = None
    if https:
        global HTTPS_CA  # the one polygon's CA, for crawl.ca_bundle tests
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ca = trustme.CA()
        ca.issue_cert("127.0.0.1", "localhost").configure_cert(context)
        HTTPS_CA = ca.cert_pem.bytes()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=context)
    loop.run_until_complete(site.start())
    port = runner.addresses[0][1]
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        yield f"{'https' if https else 'http'}://127.0.0.1:{port}"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.run_until_complete(runner.cleanup())
        loop.close()
