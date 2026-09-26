from __future__ import annotations

from enum import StrEnum

import typer

from .. import output
from ..core import hreflang as hreflang_service
from ..core import storage

Only = StrEnum("Only", {name: name for name in hreflang_service.ONLY})


@output.guard
def hreflang(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    only: Only = typer.Option(
        "all",
        "--only",
        help=(
            "all — все аннотации; non_200 — цель отвечает не 200; unlinked — на цель нет обычных ссылок; "
            "missing_return — цель не ссылается обратно; inconsistent — обратная ссылка с чужим кодом; "
            "non_canonical — цель неканоническая; noindex_return — у цели noindex; missing — HTML-страницы без hreflang."
        ),
    ),
    limit: int = typer.Option(100, "--limit", min=1, help="Сколько строк показать (всего — в поле total)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Отчёт Hreflang: языковые версии страниц — каждая аннотация с кодом и состоянием цели.

    Аннотации берутся из `<link rel="alternate" hreflang>` и заголовка Link; их сбор и
    обход целей — `collect.hreflang.store` / `.follow`. Проблемы (коды, обратные ссылки,
    x-default…) — `spider issues`, группа Hreflang; здесь — сами пары страниц для
    разбора. Считается по сохранённому обходу, сайт не скачивается.

    Примеры:
      spider hreflang
      spider hreflang --only missing_return
      spider --json hreflang 12 --only non_200 --limit 1000

    JSON: `{crawl_id, only, total, annotations: [{source, hreflang, target, target_status,
    target_blocked, target_indexability, return_link}]}`; `target_status` null — цель не
    скачивалась; `return_link` null — ссылка страницы на себя; для `missing` заполнен только
    `source`.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        total, rows = hreflang_service.report(engine, crawl_id, only.value, limit)
    data = {"crawl_id": crawl_id, "only": only.value, "total": total, "annotations": rows}
    output.emit_success(ctx, data, render_human=output.human.hreflang_list)
