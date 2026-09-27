from __future__ import annotations

import importlib
import importlib.util
from datetime import UTC, datetime

import typer

from .. import output
from ..core.errors import InvalidArguments
from ..core.version import DEV_VERSION, cli_name, installed_version

# `auth status` exists in every CLI (tools/docs/standard-release.md §8); a CLI
# generated without credentials (no credentials/ package, no commands/login.py)
# reports an empty `credentials` list and exits 0. Detected at runtime so this
# file needs no template logic — same approach as doctor.py.
_PACKAGE_NAME = __name__.split(".")[0]
_HAS_CREDENTIALS = importlib.util.find_spec(f"{_PACKAGE_NAME}.credentials") is not None

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
        None, "--provider", help="Только этот провайдер: proxy, site или database (по умолчанию — все)."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать секреты всех провайдеров: откуда берутся и работают ли. Значения не печатаются.

    Провайдеры spider — `proxy` (пароль `{password}` в `crawl.proxy_urls`), `site`
    (пароль сайта при `crawl.auth = basic`) и `database` (пароль `SPIDER_DB_URL`);
    все необязательные: нужны только при этих настройках. Без `--check` — только
    наличие (статус `unchecked` или `missing`). С `--check` — проверка без сети:
    у этих секретов нет API, которое можно спросить, поэтому найденный секрет — `ok`.

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


if importlib.util.find_spec(f"{_PACKAGE_NAME}.commands.login") is not None:
    _login = importlib.import_module(f"{_PACKAGE_NAME}.commands.login")
    app.command("login")(_login.login)
    app.command("logout")(_login.logout)
