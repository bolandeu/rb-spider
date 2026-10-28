"""The `auth` command group: `status` reports the health of the credentials of every provider, or an empty report when
the package has none.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import typer

from .. import output
from ..core.errors import InvalidArguments
from ..core.version import DEV_VERSION, cli_name, installed_version, module_exists, optional_module
from ..providers import secrets
from . import options

# `auth status` exists in every CLI (the Standard, Health); a CLI
# generated without credentials (no credentials/ package, no commands/login.py)
# reports an empty `credentials` list and exits 0. Detected at runtime so this
# file needs no template logic — same approach as doctor.py.
_PACKAGE_NAME = __name__.split(".")[0]
_HAS_CREDENTIALS = module_exists(f"{_PACKAGE_NAME}.credentials.manager")

app = output.group(
    "Секреты (пароли прокси, сайта, базы PostgreSQL) — в системном хранилище ключей, не в файлах проекта."
)


@app.command("status")
@output.guard
def auth_status(
    ctx: typer.Context,
    check: bool = typer.Option(
        False, "--check", help="Ещё и проверить каждый секрет (не дольше 10 с на провайдера), а не только его наличие."
    ),
    provider: str | None = typer.Option(
        None, "--provider", help="Только этот провайдер: proxy, proxy_key, site или database (по умолчанию — все)."
    ),
    profile: str | None = options.ProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать секреты всех провайдеров: откуда берутся и работают ли. Значения не печатаются.

    Провайдеры spider — `proxy` (пароль `{password}` в `crawl.proxy_urls`), `proxy_key`
    (ключ `{key}` в `crawl.proxy_change_ip_urls`), `site` (пароль сайта при
    `crawl.auth = basic`) и `database` (пароль `SPIDER_DATABASE_URL`); все необязательные:
    нужны только при этих настройках. Без `--check` — только наличие (статус
    `unchecked` или `missing`). С `--check`: `database` — подключение к `SPIDER_DATABASE_URL`,
    если он задан; `proxy` — по одному TCP-соединению и одному запросу через каждый адрес
    `crawl.proxy_urls` (настройки проекта и `--profile`, как у `crawl`), все сразу и не
    дольше 10 с: `ok`, если хоть один адрес ответил, иначе `invalid` с причиной; результат
    запоминается (`crawl.proxy_state_ttl_s`), его показывает `spider doctor`; у `proxy_key`
    и `site` спросить некого (их проверяет только обход), найденный секрет — `ok`.

    Коды выхода: 0 — все обязательные провайдеры в порядке (необязательный может
    отсутствовать); 3 — у обязательного проблема или какой-то секрет `invalid` /
    `expired`; 2 — неизвестный `--provider`.

    JSON — общий для всех наших инструментов контракт: `tool`, `version`, `checked_at`,
    `credentials[]` с `provider`, `required`, `fields`, `source`, `source_ref`, `status`,
    `expires_at`, `quota`, `message`.

    Example: {cli} auth status --check --json
    Example: {cli} auth status --provider proxy
    """
    tool, version = cli_name(), installed_version() or DEV_VERSION
    secrets.use_crawl_settings(lambda: options.resolve(ctx, profile, None, None).settings.crawl)
    if not _HAS_CREDENTIALS:
        if provider is not None:
            raise InvalidArguments(f"Unknown provider '{provider}' ({tool} stores no credentials).")
        checked_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        payload = {"tool": tool, "version": version, "checked_at": checked_at, "credentials": []}
        output.emit_report(ctx, payload, lambda _: output.human.echo(f"{tool} stores no credentials."), None)
        return
    health = importlib.import_module(f"{_PACKAGE_NAME}.credentials.health")
    payload, problem = health.status(tool, version, check=check, only=provider)
    output.emit_report(ctx, payload, health.render, problem)


if _login := optional_module(f"{_PACKAGE_NAME}.commands.login"):
    app.command("login")(_login.login)
    app.command("logout")(_login.logout)
