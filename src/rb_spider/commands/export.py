from __future__ import annotations

import sys
from enum import StrEnum
from itertools import islice
from pathlib import Path

import typer

from .. import output
from ..core import export as export_service
from ..core import overview as overview_service
from ..core import storage
from ..core.extract import normalize_url


class Format(StrEnum):
    csv = "csv"
    json = "json"


class Dataset(StrEnum):
    pages = "pages"
    links = "links"
    issues = "issues"


OutputOption = typer.Option(
    None, "--output", "-o", help="Записать в файл; без него — поток данных в stdout (без JSON-конверта)."
)


def _stream(ctx: typer.Context, table: export_service.Table, fmt: Format, path: Path | None, meta: dict) -> None:
    """Stream to stdout (data only), or to a file with a summary (`{..., format, rows, path}`) as the result."""
    if path is None:
        export_service.write(table, fmt.value, sys.stdout)
        return
    with path.open("w", encoding="utf-8", newline="") as out:
        rows = export_service.write(table, fmt.value, out)
    data = {**meta, "format": fmt.value, "rows": rows, "path": str(path)}
    output.emit_success(ctx, data, render_human=output.human.exported)


@output.guard
def url(
    ctx: typer.Context,
    page_url: str = typer.Argument(..., metavar="URL", help="URL из обхода, например https://example.com/catalog/."),
    crawl_id: int | None = typer.Option(None, "--crawl", help="Номер обхода; по умолчанию — последний."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Всё об одном URL: ответ и заголовки, on-page данные, индексируемость, проблемы, ссылки, ресурсы.

    Последний шаг drill-down: `spider issues` → `spider urls --issue <код>` →
    `spider url <url>`. Сами ссылки страницы — `spider links <url> --in|--out`,
    шаги редиректа — `spider redirects`.

    Примеры:
      spider url https://example.com/
      spider --json url https://example.com/catalog/ --crawl 12

    JSON: `{crawl_id, page: {url, status_code, response_ms, last_modified, headers,
    indexable, indexability_status, title, …все колонки страницы}, request_headers,
    issues: [{code, name, type, priority, detail}], inlinks,
    outlinks, resources: [{target, kind, alt, alt_attr, sized, status_code, bytes}],
    metrics: [{source, name, value, text}]}`; `inlinks` / `outlinks` — число обычных
    ссылок на страницу и с неё, `metrics` — от обогатителей (`spider enrich`). URL нет
    в обходе — выход 2.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        data = export_service.url_details(engine, crawl_id, normalize_url(page_url))
    output.emit_success(ctx, data, render_human=output.human.url_details)


@output.guard
def export(
    ctx: typer.Context,
    what: Dataset = typer.Argument(Dataset.pages, help="Что выгрузить: pages (URL), links (ссылки), issues (находки)."),
    crawl_id: int | None = typer.Option(None, "--crawl", help="Номер обхода; по умолчанию — последний."),
    fmt: Format = typer.Option(Format.csv, "--format", help="csv (с заголовком) или json (массив объектов)."),
    path: Path | None = OutputOption,
    issue: str | None = typer.Option(
        None, "--issue", help="Только URL (pages) или находки (issues) этой проверки из `spider issues`."
    ),
    target_status: str | None = typer.Option(
        None, "--status", help="Код ответа: 404 или класс 4xx — у URL (pages) или у цели ссылки (links)."
    ),
    external: bool = typer.Option(False, "--external", help="Только чужие сайты: внешние URL или ссылки на них."),
    kind: str | None = typer.Option(
        None, "--type", help="Только URL этого типа (pages): html, js, css, image, pdf, other, unknown."
    ),
    scheme: str | None = typer.Option(None, "--scheme", help="Только URL по этому протоколу (pages): https или http."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Выгрузить данные обхода в CSV или JSON: URL, ссылки или находки проверок.

    Для таблиц и сторонних инструментов; вопрос к данным точнее задать
    `spider query`. Данные идут потоком — выгрузка любого размера не занимает
    память. Колонки pages — все данные страницы (как в `spider url`) и тип
    `content_kind` (html, js, css, image, pdf, other, unknown), links —
    ссылки с кодом ответа цели (`target_status`), issues — находки с названием,
    типом и приоритетом проверки.

    Примеры:
      spider export > pages.csv                                # все URL последнего обхода
      spider export issues -o issues.csv                       # все сработавшие проверки
      spider export pages --issue page_title_missing --format json
      spider export links --status 404 -o links-to-404.csv     # кто ссылается на 404
      spider export links --external                           # все внешние ссылки
      spider export pages --type css --status 4xx              # битые стили
      spider export pages --scheme http                        # что осталось на HTTP

    Без `-o` в stdout идут только данные (флаг `--json` их не оборачивает). С `-o`
    печатается итог; JSON: `{crawl_id, dataset, format, rows, path}`. Неизвестная
    проверка или тип, неверный `--status`, `--issue` для links, `--type` / `--scheme` не
    для pages — выход 2.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        with engine.connect() as conn:
            table = export_service.dataset(
                conn,
                crawl_id,
                what.value,
                issue=issue,
                target_status=target_status,
                external=external,
                kind=kind,
                scheme=scheme,
            )
            _stream(ctx, table, fmt, path, {"crawl_id": crawl_id, "dataset": what.value})


@output.guard
def query(
    ctx: typer.Context,
    sql: str = typer.Argument(..., help="Запрос SELECT (или WITH … SELECT) к базе обходов."),
    limit: int = typer.Option(1000, "--limit", min=1, help="Сколько строк показать (без --format)."),
    fmt: Format | None = typer.Option(None, "--format", help="Выгрузить все строки потоком: csv или json."),
    path: Path | None = OutputOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Выполнить свой SQL-запрос к базе обходов — только чтение.

    Для вопросов, на которые нет готовой команды. База открывается только для
    чтения, а SQLite сам отклоняет всё, кроме SELECT: запись, ATTACH, PRAGMA.
    Таблицы: pages, links, issues, url_metrics, crawls, projects, frontier; у строк
    обхода — `crawl_id` (`spider crawls list`). `links` — представление с URL
    текстом (source, target); хранятся ссылки в link_rows по id из urls — для
    тяжёлых запросов быстрее группировать link_rows по source_id / target_id и
    соединять с urls в конце. Колонки — `spider export` с тем же набором или
    `SELECT * FROM pages LIMIT 1`. Функция casefold(x) — регистр без учёта кириллицы.

    Примеры:
      spider query "SELECT status_code, count(*) FROM pages WHERE crawl_id = 3 GROUP BY 1"
      spider --json query "SELECT url, word_count FROM pages WHERE crawl_id = 3 ORDER BY 2 LIMIT 20"
      spider query "SELECT source, target FROM links WHERE crawl_id = 3 AND anchor = ''" --format csv -o empty.csv

    Выход — таблица (не больше `--limit` строк); JSON: `{columns, rows, truncated}`,
    `rows` — массивы значений. С `--format` строки идут потоком без ограничения —
    в stdout или в файл `-o` (тогда итог `{format, rows, path}`). Ошибка в
    запросе или попытка записи — выход 2.
    """
    with export_service.read_only() as conn:
        table = export_service.query(conn, sql)
        if fmt is not None or path is not None:
            _stream(ctx, table, fmt or Format.csv, path, {})
            return
        rows = [list(row) for row in islice(table.rows, limit + 1)]
    data = {"columns": table.columns, "rows": rows[:limit], "truncated": len(rows) > limit}
    output.emit_success(ctx, data, render_human=output.human.query_table)


@output.guard
def overview(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сводка обхода: сколько URL и каких — типы, коды ответа, индексируемость, canonical, директивы, глубина.

    Первый взгляд на обход (как Crawl Overview в Screaming Frog) — до `spider
    issues`. Только числа по URL сайта (и отдельно типы чужих URL); сами списки —
    `spider export pages --type css`, `--status 4xx`, `spider urls --issue <код>`,
    `spider query`.

    Примеры:
      spider overview
      spider --json overview 12

    JSON: `{crawl_id, totals: {stored, internal, external, blocked_by_robots,
    no_response, indexable, queued_ever, still_queued}, content_types,
    external_content_types, status, indexability, canonicals, directives, depth, hreflang, pagination, security}`;
    разделы — `{значение: число URL}`: status — 2xx…5xx, blocked, no_response;
    canonicals — missing / self_referencing / canonicalised; directives, depth и hreflang
    (contains / missing, пусто — hreflang на сайте нет; списки — `spider hreflang`) — среди
    HTML-страниц сайта с кодом 200; pagination — contains / first_page / paginated (страницы
    2+) по rel next/prev, пусто — пагинации нет; security — URL сайта по https / http
    (список — `spider export pages --scheme http`). Нет обхода — выход 2.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        data = overview_service.overview(engine, crawl_id)
    output.emit_success(ctx, data, render_human=output.human.overview)
