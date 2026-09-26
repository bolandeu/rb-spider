from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ..core.models import ProjectConfig

app = output.group("Настройки проекта (`.spider/config.toml`).")


@app.command("list")
@output.guard
def list_config(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать все настройки проекта.

    Пример: spider config list

    JSON: объект конфига целиком.
    """
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.require_project_root(start)
    config = services.load_config(root)
    data = config.model_dump()
    output.emit_success(ctx, data, render_human=lambda d: output.human.key_values("Config", d))


@app.command("get")
@output.guard
def get_config(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Ключ через точку, например provider.name."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать одну настройку по ключу.

    Пример: spider config get provider.name

    JSON: `{key, value}`. Неизвестный ключ — код выхода 2.
    """
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.require_project_root(start)
    value: object = services.load_config(root).model_dump()
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise InvalidArguments(f"Unknown config key '{key}'.")
        value = value[part]
    output.emit_success(
        ctx, {"key": key, "value": value}, render_human=lambda d: output.human.echo(f"{d['key']} = {d['value']}")
    )


@app.command("set")
@output.guard
def set_config(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Ключ через точку, например provider.name."),
    value: str = typer.Argument(..., help="Новое значение (сохраняется строкой)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить одну настройку проекта. Только не секреты: пароли и ключи — `spider auth login`.

    Пример: spider config set provider.name proxy-main

    JSON: `{key, value}`. Неизвестный ключ — код выхода 2.
    """
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.require_project_root(start)
    data = services.load_config(root).model_dump()
    parts = key.split(".")
    target = data
    for part in parts[:-1]:
        if not isinstance(target, dict) or part not in target:
            raise InvalidArguments(f"Unknown config key '{key}'.")
        target = target[part]
    if not isinstance(target, dict) or parts[-1] not in target:
        raise InvalidArguments(f"Unknown config key '{key}'.")
    target[parts[-1]] = value
    services.save_config(root, ProjectConfig.model_validate(data))
    output.emit_success(
        ctx, {"key": key, "value": value}, render_human=lambda d: output.human.echo(f"Set {d['key']} = {d['value']}")
    )
