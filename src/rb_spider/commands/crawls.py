from __future__ import annotations

import typer

from .. import output
from ..core import storage

app = output.group("Обходы в базе: список (дальше — просмотр, удаление, чистка).")


@app.command("list")
@output.guard
def list_crawls(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit", min=1, help="Сколько последних обходов показать."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать обходы всех проектов, новые сверху.

    Примеры:
      spider crawls list
      spider --json crawls list --limit 5

    JSON: `{crawls: [{id, project, start_url, status, started_at, finished_at, pages}]}`,
    даты — ISO 8601 в UTC; `status` — running | finished | failed | interrupted.
    """
    with storage.database() as engine:
        rows = storage.list_crawls(engine, limit=limit)
    data = {
        "crawls": [
            {
                **vars(row),
                "started_at": row.started_at.isoformat(),
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in rows
        ]
    }
    output.emit_success(ctx, data, render_human=lambda d: output.human.crawls_table(d["crawls"]))
