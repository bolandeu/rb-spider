from __future__ import annotations

from enum import StrEnum

import typer

from .. import output
from ..core import storage
from ..core.extract import normalize_url


class Direction(StrEnum):
    out = "out"
    in_ = "in"


@output.guard
def links(
    ctx: typer.Context,
    url: str = typer.Argument(..., help="URL страницы из обхода, например https://example.com/catalog/."),
    crawl_id: int | None = typer.Option(None, "--crawl", help="Номер обхода; по умолчанию — последний."),
    inbound: bool = typer.Option(False, "--in", help="Входящие ссылки: какие страницы ведут на URL."),
    outbound: bool = typer.Option(False, "--out", help="Исходящие ссылки: куда ведёт URL (по умолчанию)."),
    limit: int = typer.Option(100, "--limit", min=1, help="Сколько ссылок показать (всего — в поле total)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Ссылки страницы: исходящие (`--out`) или входящие (`--in`), с анкором и кодом ответа.

    Кроме обычных <a href> в списке canonical, редиректы, refresh, hreflang,
    rel=next/prev, формы (`kind`). Хранятся, если `collect.internal_links.store` /
    `collect.external_links.store` включены (по умолчанию да). У обычных ссылок —
    зона страницы (`position`: nav, header, footer, sidebar, content — по
    `custom.link_positions`) и, с `collect.link_path`, путь её предков. Пример
    вопроса: «кто ссылается на эту 404» — `spider links <404-url> --in`.

    Example: spider links https://example.com/
    Example: spider links https://example.com/old-page --in
    Example: spider --json links https://example.com/ --out --limit 500

    JSON: `{crawl_id, url, direction, total, links: [{source, target, kind, anchor, alt,
    rel, nofollow, internal, position, path, status_code}]}`; `status_code` — код URL на другом конце
    ссылки (null — не скачивался). `--in` и `--out` вместе — выход 2.
    """
    if inbound and outbound:
        from ..core.errors import InvalidArguments

        raise InvalidArguments("Choose one direction: --in or --out.")
    direction = Direction.in_ if inbound else Direction.out
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        total, rows = storage.links_of(engine, crawl_id, normalize_url(url), direction.value, limit)
    data = {
        "crawl_id": crawl_id,
        "url": normalize_url(url),
        "direction": direction.value,
        "total": total,
        "links": rows,
    }
    output.emit_success(ctx, data, render_human=output.human.links_table)
