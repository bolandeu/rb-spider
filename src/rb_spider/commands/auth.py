from __future__ import annotations

import typer

from .. import output
from ..core.errors import InvalidArguments
from ..credentials import manager as credentials

app = output.group("Секреты (пароли прокси, DSN баз) — в системном хранилище ключей, не в файлах проекта.")


@app.command("login")
@output.guard
def login(
    ctx: typer.Context,
    provider: str = typer.Option("default", "--provider", help="Имя учётной записи, например proxy-main."),
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сохранить секрет в системное хранилище ключей (keychain).

    Значение берётся из переменной окружения `SPIDER_<PROVIDER>_API_KEY`,
    иначе спрашивается интерактивно (с `--non-interactive` — ошибка, код 2).

    Примеры:
      spider auth login --provider proxy-main
      SPIDER_PROXY_MAIN_API_KEY=... spider auth login --provider proxy-main --non-interactive

    JSON: `{provider}`.
    """
    secret = credentials.read_secret_from_env(provider)
    if secret is None:
        if ctx.obj.get("non_interactive") or non_interactive:
            raise InvalidArguments(
                f"No credential found in environment for provider '{provider}' and --non-interactive was set."
            )
        secret = typer.prompt(f"Enter API key for '{provider}'", hide_input=True)
    credentials.store_secret(provider, secret)
    output.emit_success(
        ctx,
        {"provider": provider},
        render_human=lambda d: output.human.echo(f"Stored credential for '{d['provider']}'."),
    )


@app.command("logout")
@output.guard
def logout(
    ctx: typer.Context,
    provider: str = typer.Option("default", "--provider", help="Имя учётной записи, например proxy-main."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить секрет из системного хранилища ключей.

    Пример: spider auth logout --provider proxy-main

    JSON: `{provider}`.
    """
    credentials.delete_secret(provider)
    output.emit_success(
        ctx,
        {"provider": provider},
        render_human=lambda d: output.human.echo(f"Removed credential for '{d['provider']}'."),
    )


@app.command("status")
@output.guard
def auth_status(
    ctx: typer.Context,
    provider: str = typer.Option("default", "--provider", help="Имя учётной записи, например proxy-main."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Проверить, доступен ли секрет (из keychain или переменной окружения).

    Пример: spider auth status --provider proxy-main

    JSON: `{provider, authenticated}`.
    """
    authenticated = credentials.get_secret(provider) is not None
    output.emit_success(
        ctx,
        {"provider": provider, "authenticated": authenticated},
        render_human=lambda d: output.human.echo(
            f"{'Authenticated' if d['authenticated'] else 'Not authenticated'} for '{d['provider']}'."
        ),
    )
