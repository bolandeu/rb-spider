from __future__ import annotations

from enum import StrEnum

import typer

from .. import output
from ..core import pagination as pagination_service
from ..core import storage

Only = StrEnum("Only", {name: name for name in pagination_service.ONLY})


@output.guard
def pagination(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    only: Only = typer.Option(
        "all",
        "--only",
        help="all — все rel=next / prev; non_200 — цель отвечает не 200; unlinked — на цель нет обычных ссылок.",
    ),
    limit: int = typer.Option(100, "--limit", min=1, help="Сколько строк показать (всего — в поле total)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Отчёт Pagination: ссылки rel=next / prev каждой страницы и состояние их целей.

    Ссылки берутся из `<link rel="next|prev">` и заголовка Link; их сбор и обход целей —
    `collect.pagination.store` / `.follow`. Проблемы (нет ссылки <a>, петли, несходящиеся
    пары, неиндексируемые страницы серии) — `spider issues`, группа Pagination; сколько
    страниц в сериях — `spider overview`. Считается по сохранённому обходу.

    Примеры:
      spider pagination
      spider pagination --only non_200
      spider --json pagination 12 --only unlinked --limit 1000

    JSON: `{crawl_id, only, total, links: [{source, rel, target, target_status, target_blocked,
    target_indexability}]}`; `rel` — next | prev; `target_status` null — цель не скачивалась.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        total, rows = pagination_service.report(engine, crawl_id, only.value, limit)
    data = {"crawl_id": crawl_id, "only": only.value, "total": total, "links": rows}
    output.emit_success(ctx, data, render_human=output.human.pagination_list)
