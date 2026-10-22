"""`auth login` / `auth logout` — only in CLIs generated with credentials (include_auth).

`commands/auth.py` registers these into the `auth` group when this module
exists; `auth status` is there in every CLI (the Standard, Health).
"""

from __future__ import annotations

import typer

from .. import output
from ..core.errors import InvalidArguments
from ..credentials import manager as credentials


@output.guard
def login(
    ctx: typer.Context,
    provider: str = typer.Option("default", "--provider", help="Провайдер: proxy, proxy_key, site или database."),
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сохранить секрет в системное хранилище ключей (keychain).

    Значение берётся из переменной окружения `SPIDER_<PROVIDER>_API_KEY`,
    иначе спрашивается интерактивно (с `--non-interactive` — ошибка, код 2).
    Провайдеры: `proxy` — пароль для `{password}` в `crawl.proxy_urls`, `proxy_key` —
    ключ для `{key}` в `crawl.proxy_change_ip_urls` (смена IP), `site` — пароль сайта
    при `crawl.auth = basic`, `database` — пароль `SPIDER_DATABASE_URL`. Заменить секрет —
    ещё раз `auth login`; на сервере без keychain вместо него задают переменную
    окружения (`SPIDER_PROXY_API_KEY`, `SPIDER_PROXY_KEY_API_KEY`) — она важнее keychain.

    Example: {cli} auth login --provider proxy
    Example: {cli} auth login --provider proxy_key
    Example: SPIDER_DATABASE_API_KEY=... {cli} auth login --provider database --non-interactive

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


@output.guard
def logout(
    ctx: typer.Context,
    provider: str = typer.Option("default", "--provider", help="Провайдер: proxy, proxy_key, site или database."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить секрет из системного хранилища ключей.

    Например, прокси больше не нужен: пароль (`proxy`) и ключ смены IP (`proxy_key`).
    Переменные окружения (`SPIDER_<PROVIDER>_API_KEY`) команда не трогает — их убирают
    там, где задали. Заменить секрет — `auth login` без `logout`.

    Example: {cli} auth logout --provider proxy
    Example: {cli} auth logout --provider proxy_key

    JSON: `{provider}`.
    """
    credentials.delete_secret(provider)
    output.emit_success(
        ctx,
        {"provider": provider},
        render_human=lambda d: output.human.echo(f"Removed credential for '{d['provider']}'."),
    )
