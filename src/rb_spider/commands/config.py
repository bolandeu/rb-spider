from __future__ import annotations

import json
from pathlib import Path

import typer

from .. import output
from ..core import services, settings
from ..core.errors import InvalidArguments
from ..core.models import ProjectConfig
from . import options

app = output.group("Настройки: проектный файл, итоговые значения по слоям, проверка и схема.")


@app.command("list")
@output.guard
def list_config(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать проектный файл `.spider/config.toml` как он записан.

    Только то, что задано в проекте. Итоговые значения со всеми слоями
    (профиль, флаги, переменные окружения) — `spider config show`.

    Пример: spider config list

    JSON: содержимое файла (поля проекта и разделы настроек, например `crawl`).
    """
    root = services.require_project_root(Path(ctx.obj.get("project") or Path.cwd()))
    services.load_config(root)  # validates the file and the CLI version
    data = services.read_project_data(root)
    output.emit_success(ctx, data, render_human=lambda d: output.human.key_values("Config", settings.flatten(d)))


@app.command("get")
@output.guard
def get_config(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Ключ через точку: поле проекта (name) или настройка (crawl.max_urls)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать одно значение из проектного файла.

    Пример: spider config get crawl.concurrency

    JSON: `{key, value}`; `value` — null, если в проекте ключ не задан (действует
    значение из другого слоя — см. `spider config show`). Неизвестный ключ — выход 2.
    """
    root = services.require_project_root(Path(ctx.obj.get("project") or Path.cwd()))
    known = set(settings.flatten(ProjectConfig(name="-").model_dump())) | set(settings.settings_keys())
    if key not in known:
        raise InvalidArguments(f"Unknown config key '{key}'. Known keys: {', '.join(sorted(known))}.")
    value = settings.flatten(services.read_project_data(root)).get(key)
    output.emit_success(
        ctx, {"key": key, "value": value}, render_human=lambda d: output.human.echo(f"{d['key']} = {d['value']}")
    )


@app.command("set")
@output.guard
def set_config(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Ключ через точку: поле проекта (name) или настройка (crawl.max_urls)."),
    value: str = typer.Argument(..., help='Значение: число, true/false, "строка" или [список] в синтаксисе TOML.'),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Записать одно значение в проектный файл. Не для секретов: пароли — `spider auth login`.

    Значение разбирается как TOML (`500` — число, `false` — логическое), иначе
    сохраняется строкой. Весь файл проверяется до записи.

    Примеры:
      spider config set crawl.concurrency 10
      spider config set crawl.robots report
      spider config set name shop

    JSON: `{key, value}`. Неизвестный ключ или неверный тип — выход 2.
    """
    root = services.require_project_root(Path(ctx.obj.get("project") or Path.cwd()))
    flat = settings.flatten(services.read_project_data(root))
    flat[key] = settings.parse_value(value)
    data = settings.unflatten(flat)
    project_part = {k: v for k, v in data.items() if k not in settings.SECTIONS}
    if key.split(".")[0] in settings.SECTIONS:
        settings.resolve(root, project_data=data, environ={})  # validates the settings sections
    elif key not in settings.flatten(ProjectConfig(name="-").model_dump()):
        raise InvalidArguments(f"Unknown config key '{key}'. Settings keys: {', '.join(settings.settings_keys())}.")
    ProjectConfig.model_validate(project_part)
    services.write_project_data(root, data)
    output.emit_success(
        ctx,
        {"key": key, "value": flat[key]},
        render_human=lambda d: output.human.echo(f"Set {d['key']} = {d['value']}"),
    )


@app.command("show")
@output.guard
def show(
    ctx: typer.Context,
    profile: str | None = options.ProfileOption,
    config_file: Path | None = options.ConfigFileOption,
    assignments: list[str] | None = options.SetOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Итоговые настройки обхода и слой, откуда пришло каждое значение.

    Ровно то, с чем запустится `spider crawl` при тех же `--profile` / `--config`
    / `--set`, — проверить профиль до обхода. Слои: default, global, project,
    profile:<имя>, file:<путь>, env, flag, set.

    Примеры:
      spider config show
      spider config show --profile googlebot --set crawl.max_urls=500

    JSON: `{settings: {раздел: {ключ: значение}}, sources: {"раздел.ключ": слой}}`.
    Ошибка в любом слое — выход 2 с указанием ключа и слоя.
    """
    resolved = options.resolve(ctx, profile, config_file, assignments)
    data = {"settings": resolved.settings.model_dump(mode="json"), "sources": resolved.sources}
    output.emit_success(ctx, data, render_human=output.human.settings_table)


@app.command("validate")
@output.guard
def validate(
    ctx: typer.Context,
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="TOML-файл профиля или настроек."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Проверить файл профиля до использования: ключи, типы, цепочку `extends`.

    Примеры:
      spider config validate .spider/profiles/shop.toml
      spider --json config validate my-settings.toml

    JSON: `{file, valid: true, extends}`. Ошибки — выход 2, в сообщении каждый
    неверный ключ и причина.
    """
    profile = settings.load_profile_file(file, str(file))
    if profile.extends:
        root = services.find_project_root(Path(ctx.obj.get("project") or Path.cwd()))
        settings.profile_layers(profile.extends, root)  # the parent chain must exist and be valid too
    output.emit_success(
        ctx,
        {"file": str(file), "valid": True, "extends": profile.extends},
        render_human=lambda d: output.human.echo(f"{d['file']}: ok"),
    )


@app.command("schema")
@output.guard
def schema(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """JSON Schema файла профиля: все ключи, типы, значения по умолчанию, описания.

    По ней агент составляет корректный профиль без угадывания. Всегда печатает
    саму схему (без конверта `{ok}`), чтобы её можно было сразу сохранить в файл.

    Примеры:
      spider config schema
      spider config schema > spider-profile.schema.json
    """
    typer.echo(json.dumps(settings.ProfileFile.model_json_schema(), ensure_ascii=False, indent=2))
