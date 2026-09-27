from __future__ import annotations

from dataclasses import asdict
from enum import StrEnum
from pathlib import Path

import typer

from .. import output
from ..core import redirects as redirects_service
from ..core import storage
from . import options


class Only(StrEnum):
    all = "all"
    chains = "chains"
    errors = "errors"


@output.guard
def redirects(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    only: Only = typer.Option(
        Only.all, "--only", help="all — все редиректы; chains — цепочки и петли; errors — ведут на ошибку."
    ),
    limit: int = typer.Option(100, "--limit", min=1, help="Сколько редиректов показать (всего — в поле total)."),
    canonicals: bool = typer.Option(
        False, "--canonicals", help="Считать шагом и canonical на другой URL (Redirect & Canonical Chains)."
    ),
    profile: str | None = options.ProfileOption,
    config_file: Path | None = options.ConfigFileOption,
    assignments: list[str] | None = options.SetOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Отчёт по редиректам: каждый редирект по шагам до конечного URL и его кода.

    Прыжок — серверный 3xx или meta / HTTP Refresh, с `--canonicals` — ещё и canonical
    на другой URL (Redirect & Canonical Chains). `chains` — цепочки от
    `thresholds.redirect_chain_hops` прыжков (по умолчанию 2) и петли; порог — из
    текущих настроек, как у `spider analyze`. `errors` — редиректы, которые
    приводят к ошибке: нет ответа, запрет robots.txt, 4xx, 5xx или петля.
    Считается по сохранённому обходу, сайт не скачивается.

    Примеры:
      spider redirects
      spider redirects --only chains
      spider redirects --only chains --canonicals
      spider --json redirects 12 --only errors

    JSON: `{crawl_id, only, total, redirects: [{url, hops: [{url, status_code, type}],
    final_url, final_status, loop, is_error}]}`; `type` — 3xx | meta | http; `final_status`
    null — конечный URL не скачивался (другой хост), `final_url` null — петля; с
    `--canonicals` type бывает canonical.
    """
    thresholds = options.resolve(ctx, profile, config_file, assignments).settings.thresholds
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        found = redirects_service.report(engine, crawl_id, only.value, thresholds, canonicals)
    data = {
        "crawl_id": crawl_id,
        "only": only.value,
        "total": len(found),
        "redirects": [{**asdict(r), "is_error": r.is_error} for r in found[:limit]],
    }
    output.emit_success(ctx, data, render_human=output.human.redirects_list)
