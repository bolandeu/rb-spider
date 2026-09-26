from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import services


@output.guard
def status(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Показать проект, найденный от текущего каталога (или `--project`).

    Примеры:
      spider status
      spider --json status

    JSON: `{project, path, provider}`. Нет проекта — код выхода 4, подсказка `spider init`.
    """
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.require_project_root(start)
    output.vecho(ctx, f"Resolved project root: {root}")
    config = services.load_config(root)
    output.emit_success(
        ctx,
        {"project": config.name, "path": str(root), "provider": config.provider.name},
        render_human=lambda data: output.human.key_values(
            "Status",
            {"project": data["project"], "path": data["path"], "provider": data["provider"]},
        ),
    )
