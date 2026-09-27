from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import crawl as crawl_service
from ..core import services, storage


@output.guard
def status(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода; по умолчанию — последний."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Прогресс обхода и проект: сколько URL сохранено, сколько ждёт в очереди, жив ли процесс.

    Для обхода в фоне (`spider crawl --detach`) — основной способ следить за ним.
    Данные в базе обновляются во время обхода каждые ~2 с. Проект — если команда
    запущена в каталоге проекта (или с `--project`), иначе null.

    Example: spider status
    Example: spider --json status 12

    JSON: `{project, path, crawl: {id, project, start_url, status, pages, pending, pid,
    alive}}`; `crawl` null — обходов ещё нет. `alive` — жив ли процесс обхода (null —
    не определить, например на Windows). Статус running при `alive: false` — процесс
    умер, обход можно продолжить: `spider crawls resume <id>`.
    """
    root = services.find_project_root(Path(ctx.obj.get("project") or Path.cwd()))
    output.vecho(ctx, f"Resolved project root: {root}")
    config = services.load_config(root) if root else None
    crawl = None
    with storage.database() as engine:
        if crawl_id is not None or storage.list_crawls(engine, limit=1):
            crawl_id = storage.resolve_crawl_id(engine, crawl_id)
            row, _ = storage.get_crawl(engine, crawl_id)
            now = storage.progress(engine, crawl_id)
            pid = storage.crawl_pid(engine, crawl_id)
            crawl = {
                "id": row.id,
                "project": row.project,
                "start_url": row.start_url,
                "status": row.status,
                "pages": now.pages,
                "pending": now.pending,
                "pid": pid,
                "alive": crawl_service.process_alive(pid) if row.status == "running" else False,
            }
    data = {"project": config.name if config else None, "path": str(root) if root else None, "crawl": crawl}
    output.emit_success(ctx, data, render_human=output.human.status_view)
