from __future__ import annotations

import typer

from .. import output
from ..core import maintenance, storage

app = output.group("Проекты в базе обходов: список и удаление со всеми обходами.")


@app.command("list")
@output.guard
def list_projects(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать проекты: сколько обходов и страниц, когда был последний обход.

    Проект — сайт или имя из `.spider/config.toml`; все проекты живут в одной
    базе обходов (`spider db info`). Обходы проекта — `spider crawls list`.

    Example: spider projects list
    Example: spider --json projects list

    JSON: `{projects: [{name, crawls, pages, last_crawl_at}]}`, дата — ISO 8601 в UTC или null.
    """
    with storage.database() as engine:
        data = {"projects": maintenance.list_projects(engine)}
    output.emit_success(ctx, data, render_human=output.human.projects_table)


@app.command("delete")
@output.guard
def delete(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Имя проекта (`spider projects list`)."),
    dry_run: bool = output.DryRunOption,
    confirm: bool = output.ConfirmOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    non_interactive: bool = output.NonInteractiveOption,
) -> None:
    """Удалить проект со всеми его обходами и их данными.

    Необратимо: спрашивает подтверждение; `--yes` — без вопроса, `--dry-run` —
    только показать, сколько удалится. Файлы `.spider/` в каталоге проекта не
    трогаются — только данные в базе. Удалить отдельные обходы —
    `spider crawls delete`, старые — `spider crawls prune`.

    Example: spider projects delete example.com --dry-run
    Example: spider --json projects delete example.com --yes

    JSON: `{project, crawls, pages, dry_run}`. Нет проекта или его обход ещё идёт —
    выход 2; отказ в подтверждении — выход 1.
    """
    with storage.database() as engine:
        rows = maintenance.project_crawls(engine, name)
        data = {"project": name, "crawls": len(rows), "pages": sum(r.pages for r in rows),
                "dry_run": output.is_dry_run(ctx)}  # fmt: skip
        if not data["dry_run"]:
            output.require_confirmation(ctx, f"Delete project '{name}' with {len(rows)} crawl(s)", confirm)
            maintenance.delete_project(engine, name)
    output.emit_success(ctx, data, render_human=output.human.project_deletion)
