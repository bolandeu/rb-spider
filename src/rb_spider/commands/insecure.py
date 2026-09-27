from __future__ import annotations

import typer

from .. import output
from ..core import security as security_service
from ..core import storage


@output.guard
def insecure(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    limit: int = typer.Option(100, "--limit", min=1, help="Сколько строк показать (всего — в поле total)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Отчёт Insecure Content: HTTPS-страницы, которые ссылаются на HTTP-адреса или грузят с них ресурсы.

    Для перевода сайта на HTTPS: каждая ссылка, картинка, стиль, скрипт, фрейм и форма
    HTTPS-страницы, ведущие на http://. Проверки на этой основе (Mixed Content, Form URL
    Insecure) — `spider issues`, группа Security; сколько URL сайта по HTTP и HTTPS —
    `spider overview`, список — `spider export pages --scheme http`.

    Example: spider insecure
    Example: spider --json insecure 12 --limit 1000

    JSON: `{crawl_id, total, links: [{source, kind, target}]}`; `kind` — hyperlink, image,
    css, js, media, iframe, form, canonical…
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        total, rows = security_service.insecure_content(engine, crawl_id, limit)
    output.emit_success(ctx, {"crawl_id": crawl_id, "total": total, "links": rows},
                        render_human=output.human.insecure_list)  # fmt: skip
