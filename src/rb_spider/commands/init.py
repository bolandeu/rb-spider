from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import services


@output.guard
def init(
    ctx: typer.Context,
    name: str | None = typer.Option(None, "--name", help="Имя проекта; по умолчанию — имя каталога."),
    force: bool = typer.Option(False, "--force", help="Перезаписать конфиг уже инициализированного проекта."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Создать проект spider в каталоге: файл `.spider/config.toml`.

    Проект хранит настройки и данные обходов одного или нескольких сайтов.
    Каталог — текущий или заданный через `--project`. Повторный вызов ничего
    не меняет (`already_initialized: true`), `--force` пересоздаёт конфиг.

    Примеры:
      spider init
      spider --project ~/audits/shop init --name shop

    JSON: `{project, path, already_initialized}`.
    """
    target = Path(ctx.obj.get("project") or Path.cwd()).resolve()

    if not force and services.find_project_root(target) == target:
        output.vecho(ctx, f"Found existing config at {services.config_path(target)}")
        config = services.load_config(target)
        output.emit_success(
            ctx,
            {"project": config.name, "path": str(target), "already_initialized": True},
            render_human=lambda data: output.human.echo(
                f"Already initialized in {data['path']} (use --force to reset)."
            ),
        )
        return

    project_name = name or target.name
    config = services.init_project(target, project_name)
    output.emit_success(
        ctx,
        {"project": config.name, "path": str(target), "already_initialized": False},
        render_human=lambda data: output.human.key_values(
            f"Initialized project in {data['path']}", {"name": data["project"]}
        ),
    )
