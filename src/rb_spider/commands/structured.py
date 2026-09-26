from __future__ import annotations

from enum import StrEnum

import typer

from .. import output
from ..core import storage
from ..core import structured as structured_service


class Report(StrEnum):
    validation = "validation"
    features = "features"


@output.guard
def structured(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    report: Report = typer.Option(
        Report.validation,
        "--report",
        help="validation — ошибки и предупреждения (Schema.org и Google) с числом URL; features — функции "
        "расширенных результатов Google.",
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сводка микроразметки: ошибки валидации по всему обходу или функции расширенных результатов Google.

    Микроразметка собирается при обходе с `collect.structured_data` (json-ld, microdata,
    rdfa) — у обхода без неё отчёт пуст. Страницы с ошибками — `spider issues`, группа
    Structured Data; сообщения одной страницы и её разметка — `spider url` (сама разметка —
    при `--store-html`). Сравнивается со словарём Schema.org и с обязательными и
    рекомендуемыми свойствами основных функций Google (Product, Recipe, Event, FAQ…).

    Примеры:
      spider structured
      spider structured --report features
      spider --json structured 12

    JSON: `{crawl_id, report, rows}`; validation — `[{severity, scope, type, property, message,
    urls, example}]` (scope — schema.org | google; учитываются первые 50 сообщений страницы),
    features — `[{feature, urls, with_errors, with_warnings}]`.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        with engine.connect() as conn:
            rows = structured_service.summary(conn, crawl_id, report.value)
    output.emit_success(ctx, {"crawl_id": crawl_id, "report": report.value, "rows": rows},
                        render_human=output.human.structured_list)  # fmt: skip
