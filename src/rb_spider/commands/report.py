from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import typer

from .. import output
from ..core import crawl as crawl_service
from ..core import reports, storage
from ..core.errors import InvalidArguments
from ..core.extract import normalize_url
from . import options

app = output.group(
    "Отчёты по обходу: canonical, структура, время ответа, путь обхода, meta keywords, формы, заголовки, "
    "консоль JavaScript."
)
CrawlArg = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний.")
LimitOption = typer.Option(100, "--limit", min=1, help="Сколько строк показать (всего — в поле total).")
Canonicals = StrEnum("Canonicals", {name: name for name in reports.CANONICALS})
Keywords = StrEnum("Keywords", {name: name for name in reports.META_KEYWORDS})
Javascript = StrEnum("Javascript", {name: name for name in reports.JAVASCRIPT})
_KEYWORDS_HELP = (
    "all — с keywords; missing — без; multiple — несколько тегов; duplicate — одинаковые на разных страницах."
)


def _list(ctx: typer.Context, crawl_id: int, name: str, total: int, rows: list[dict], **extra) -> None:
    output.emit_success(ctx, {"crawl_id": crawl_id, "report": name, **extra, "total": total, "rows": rows},
                        render_human=output.human.report_rows)  # fmt: skip


@app.command("canonicals")
@output.guard
def canonicals(
    ctx: typer.Context,
    crawl_id: int | None = CrawlArg,
    only: Canonicals = typer.Option(
        "chains",
        "--only",
        help="chains — canonical ведёт на URL, который снова уводит; non_indexable — на "
        "неиндексируемый; all — все canonical на другой URL.",
    ),
    limit: int = LimitOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Canonical Chains и Non-Indexable Canonicals: страницы с canonical на другой URL и что с этим URL.

    Цепочка — canonical ведёт на страницу, которая сама canonical-ит дальше или
    редиректит; поисковик может не дойти до конца. Цепочки вместе с редиректами —
    `spider redirects --canonicals`.

    Примеры:
      spider report canonicals
      spider --json report canonicals --only non_indexable

    JSON: `{crawl_id, report, only, total, rows: [{url, canonical, canonical_status,
    canonical_indexability, next_hop}]}`; next_hop — куда ведёт сам canonical.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        total, rows = reports.canonicals(engine, crawl_id, only.value, limit)
    _list(ctx, crawl_id, "canonicals", total, rows, only=only.value)


@app.command("structure")
@output.guard
def structure(
    ctx: typer.Context,
    crawl_id: int | None = CrawlArg,
    depth: int = typer.Option(2, "--depth", min=1, max=10, help="До скольких уровней папок группировать URL."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Site Structure: папки сайта с числом URL (индексируемых и нет) и URL по глубине обхода.

    Где сосредоточены страницы и неиндексируемые разделы. Папка — первые `--depth`
    сегментов пути (страница `/a/b/c` — в папке `/a/b/`).

    Примеры:
      spider report structure
      spider --json report structure --depth 3

    JSON: `{crawl_id, folders: [{folder, urls, indexable, non_indexable}], depths: {глубина:
    число URL}}`.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        data = reports.structure(engine, crawl_id, depth)
    output.emit_success(ctx, {"crawl_id": crawl_id, **data}, render_human=output.human.report_structure)


@app.command("response-times")
@output.guard
def response_times(
    ctx: typer.Context,
    crawl_id: int | None = CrawlArg,
    slowest: int = typer.Option(20, "--slowest", min=1, help="Сколько самых медленных URL показать."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Response Times: URL сайта по диапазонам времени ответа и самые медленные.

    Время — от запроса до заголовков ответа, как его видел обход (при `concurrency`
    обхода, а не одиночным запросом).

    Примеры:
      spider report response-times
      spider --json report response-times --slowest 100

    JSON: `{crawl_id, urls, average_ms, max_ms, bands: {"<100": n, …, ">=5000": n},
    slowest: [{url, response_ms, status_code}]}`.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        data = reports.response_times(engine, crawl_id, slowest)
    output.emit_success(ctx, {"crawl_id": crawl_id, **data}, render_human=output.human.report_response_times)


@app.command("crawl-path")
@output.guard
def crawl_path(
    ctx: typer.Context,
    url: str = typer.Argument(..., help="URL из обхода."),
    crawl_id: int | None = typer.Option(None, "--crawl", help="Номер обхода; по умолчанию — последний."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Crawl Path: кратчайший путь, которым обход нашёл URL — от стартовой страницы по кликам.

    Почему страница так глубоко и через что до неё добраться. Каждый шаг — страница на
    клик ближе к старту, которая ссылается (или редиректит, canonical-ит…) на следующую.

    Примеры:
      spider report crawl-path https://example.com/deep/page
      spider --json report crawl-path https://example.com/x --crawl 12

    JSON: `{crawl_id, url, path: [{url, depth, via}]}`, от стартовой страницы к URL; via — как
    на этот шаг пришли с предыдущего (hyperlink, redirect, canonical…), у стартовой null.
    URL нет в обходе — выход 2.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        path = reports.crawl_path(engine, crawl_id, normalize_url(url))
    output.emit_success(ctx, {"crawl_id": crawl_id, "url": url, "path": path}, render_human=output.human.report_path)


@app.command("meta-keywords")
@output.guard
def meta_keywords(
    ctx: typer.Context,
    crawl_id: int | None = CrawlArg,
    only: Keywords = typer.Option(
        "all",
        "--only",
        help="all — с keywords; missing — без; multiple — несколько тегов; "
        "duplicate — одинаковые на нескольких страницах.",
    ),
    limit: int = LimitOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Meta Keywords: `<meta name="keywords">` HTML-страниц — есть, нет, несколько, одинаковые.

    Google keywords не учитывает; Яндекс учитывает слабо. Полезно, чтобы найти мусор и
    дубли от шаблонов CMS.

    Примеры:
      spider report meta-keywords --only duplicate
      spider --json report meta-keywords --only missing

    JSON: `{crawl_id, report, only, total, rows: [{url, keywords, tags}]}`.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        total, rows = reports.meta_keywords(engine, crawl_id, only.value, limit)
    _list(ctx, crawl_id, "meta-keywords", total, rows, only=only.value)


@app.command("forms")
@output.guard
def forms(
    ctx: typer.Context,
    crawl_id: int | None = CrawlArg,
    limit: int = LimitOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Forms: формы сайта — на какой странице и куда отправляются, по HTTP или HTTPS.

    Формы хранятся со ссылками своего вида (`collect.internal_links.store` /
    `external_links.store`). Проблемы форм — `spider issues`, группа Security.

    Примеры:
      spider report forms
      spider --json report forms --limit 1000

    JSON: `{crawl_id, report, total, rows: [{page, action, internal, insecure}]}`.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        total, rows = reports.forms(engine, crawl_id, limit)
    _list(ctx, crawl_id, "forms", total, rows)


@app.command("headers")
@output.guard
def headers(
    ctx: typer.Context,
    crawl_id: int | None = CrawlArg,
    cookies: bool = typer.Option(False, "--cookies", help="Cookie Summary: cookies вместо заголовков."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """HTTP Header Summary / Cookie Summary: заголовки ответов (или cookies) и сколько URL их отдают.

    Заголовки каждого URL — `spider url`, все построчно — `spider export headers` /
    `spider export cookies`.

    Примеры:
      spider report headers
      spider --json report headers --cookies

    JSON: `{crawl_id, cookies, rows: [{name, urls, example, attributes?}]}`; attributes — у
    cookies: какие атрибуты встречались (path, domain, secure, httponly, samesite…).
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        rows = reports.headers_summary(engine, crawl_id, cookies)
    output.emit_success(ctx, {"crawl_id": crawl_id, "cookies": cookies, "rows": rows},
                        render_human=output.human.report_headers)  # fmt: skip


@app.command("javascript")
@output.guard
def javascript(
    ctx: typer.Context,
    crawl_id: int | None = CrawlArg,
    only: Javascript = typer.Option(
        "console",
        "--only",
        help="console — ошибки и предупреждения консоли браузера; resources — ресурсы, которые браузер не "
        "загрузил (robots.txt, ошибка, 4xx / 5xx).",
    ),
    url: str | None = typer.Option(None, "--url", help="Только эта страница, каждое сообщение отдельной строкой."),
    limit: int = LimitOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Chrome Console Log Summary: ошибки JavaScript и незагруженные ресурсы при рендеринге.

    Есть только у обхода с рендерингом (`--render always|auto`). Одинаковые сообщения
    сгруппированы: сколько страниц их выдали и пример страницы. Ресурсы, закрытые
    robots.txt (kind blocked), браузер не загружал, как не загрузил бы Googlebot — это
    проверка «JavaScript: Pages with Blocked Resources». Всё построчно — `spider export
    javascript`.

    Примеры:
      spider report javascript
      spider report javascript --only resources
      spider --json report javascript --url https://example.com/app

    JSON: `{crawl_id, report, only, total, rows}`; console — rows `[{kind, message, pages,
    example}]`, resources — `[{resource, kind, reason, pages, example}]`, с `--url` —
    `[{kind, message, resource}]`. kind: error | warning | blocked | failed.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        total, rows = reports.javascript(engine, crawl_id, only.value, normalize_url(url) if url else None, limit)
    _list(ctx, crawl_id, "javascript", total, rows, only=only.value)


@output.guard
def robots_test(
    ctx: typer.Context,
    urls: list[str] = typer.Argument(..., help="URL, которые проверить."),
    robots_file: Path | None = typer.Option(
        None, "--robots", help="Свой robots.txt вместо настоящего — проверить правку до выкладки."
    ),
    user_agent: str | None = typer.Option(
        None, "--user-agent", help="От чьего имени читать правила (иначе crawl.robots_user_agent / user_agent)."
    ),
    profile: str | None = options.ProfileOption,
    config_file: Path | None = options.ConfigFileOption,
    assignments: list[str] | None = options.SetOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Robots.txt tester: разрешён ли URL для робота и какая строка robots.txt это решает.

    Качает robots.txt сайтов из списка (или берёт `--robots`), не обходит сайт. User-Agent —
    как у обхода: `--user-agent`, `crawl.robots_user_agent` или `crawl.user_agent` (пресеты
    googlebot, yandexbot…).

    Примеры:
      spider robots-test https://example.com/cart https://example.com/catalog/
      spider robots-test https://example.com/x --user-agent Googlebot --robots new-robots.txt

    JSON: `{rows: [{url, allowed, rule, user_agent}]}`; rule — решившая строка («Disallow:
    /cart»), null — ни одна не подошла (разрешено). Нет файла `--robots` — выход 2.
    """
    crawl = options.resolve(ctx, profile, config_file, assignments).settings.crawl
    if user_agent:
        crawl = crawl.model_copy(update={"robots_user_agent": user_agent})
    if robots_file is not None and not robots_file.is_file():
        raise InvalidArguments(f"--robots: no file '{robots_file}'.")
    text = robots_file.read_text(encoding="utf-8") if robots_file else None
    rows = crawl_service.test_robots(crawl, [normalize_url(u) for u in urls], text)
    output.emit_success(ctx, {"rows": rows}, render_human=output.human.robots_rows)
