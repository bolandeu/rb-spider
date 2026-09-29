from __future__ import annotations

import tomllib
from pathlib import Path

import typer

from .. import output
from ..core import services, settings
from ..core.errors import InvalidArguments

app = output.group(
    "Профили настроек обхода: встроенные пресеты, свои для всех проектов и свои в `.spider/profiles/` проекта."
)


def _root(ctx: typer.Context) -> Path | None:
    return services.find_project_root(Path(ctx.obj.get("project") or Path.cwd()))


@app.command("list")
@output.guard
def list_profiles(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать доступные профили: встроенные, свои для всех проектов и профили текущего проекта.

    Свои для всех проектов (`spider profiles init --user`) лежат в папке настроек
    пользователя: `~/.config/spider/profiles/` на Linux, `~/Library/Application
    Support/spider/profiles/` на macOS. Профиль с тем же именем заменяет менее
    близкий: проектный — пользовательский, пользовательский — встроенный.

    Example: spider profiles list

    JSON: `{profiles: [{name, where, extends, description, path}]}`; `where` —
    builtin | user | project.
    """
    rows = []
    for name, (where, path) in sorted(settings.available_profiles(_root(ctx)).items()):
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "name": name,
                "where": where,
                "extends": raw.get("extends"),
                "description": raw.get("description"),
                "path": str(path),
            }
        )
    output.emit_success(ctx, {"profiles": rows}, render_human=output.human.profiles_table)


@app.command("show")
@output.guard
def show_profile(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Имя профиля из `spider profiles list`."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать профиль: цепочку наследования и что задаёт каждый её уровень.

    Итог вместе с остальными слоями (проект, флаги) — `spider config show --profile <имя>`.

    Example: spider profiles show googlebot

    JSON: `{name, chain: [{profile, settings}]}` — от самого общего предка к профилю.
    Нет профиля или цикл в `extends` — выход 2.
    """
    layers = settings.profile_layers(name, _root(ctx))
    data = {"name": name, "chain": [{"profile": label.removeprefix("profile:"), "settings": d} for label, d in layers]}
    output.emit_success(ctx, data, render_human=output.human.profile_chain)


@app.command("init")
@output.guard
def init_profile(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Имя нового профиля (станет файлом `.spider/profiles/<имя>.toml`)."),
    from_profile: str = typer.Option("default", "--from", help="От какого профиля наследовать (`extends`)."),
    user: bool = typer.Option(
        False, "--user", help="Профиль для всех проектов — в папке настроек пользователя, проект не нужен."
    ),
    force: bool = typer.Option(False, "--force", help="Перезаписать существующий файл профиля."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать профиль: шаблон, где все ключи закомментированы и описаны.

    Раскомментируйте и поменяйте нужные ключи — остальные наследуются из
    `--from`. Профиль проекта (`.spider/profiles/`) требует проект (`spider init`);
    `--user` — профиль для всех проектов, например прокси: `~/.config/spider/profiles/`
    на Linux, `~/Library/Application Support/spider/profiles/` на macOS.

    Example: spider profiles init shop
    Example: spider profiles init shop-mobile --from googlebot
    Example: spider profiles init mobile-proxy --user

    JSON: `{name, path, extends}`. Файл уже есть (без `--force`) или нет
    профиля `--from` — выход 2; нет проекта (без `--user`) — выход 4.
    """
    if user:
        root = _root(ctx)
        folder = settings.user_profiles_dir()
    else:
        root = services.require_project_root(Path(ctx.obj.get("project") or Path.cwd()))
        folder = root / services.PROJECT_DIR_NAME / "profiles"
    settings.profile_layers(from_profile, root)  # the parent must exist
    path = folder / f"{name}.toml"
    if path.exists() and not force:
        raise InvalidArguments(f"Profile file already exists: {path} (use --force to overwrite).")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.profile_template(name, from_profile), encoding="utf-8")
    output.emit_success(
        ctx,
        {"name": name, "path": str(path), "extends": from_profile},
        render_human=lambda d: output.human.echo(f"Создан профиль {d['name']}: {d['path']}"),
    )
