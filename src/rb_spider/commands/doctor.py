from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import typer

from .. import output
from ..core import crawl as crawl_service
from ..core import services, settings, storage
from ..core.errors import CliError, CliTooOld
from ..core.models import ProjectConfig
from ..core.version import DEV_VERSION, cli_name, installed_version

_PACKAGE_NAME = __name__.split(".")[0]


def _auth_checks(needed: list[str]) -> list[dict]:
    """The keychain, plus every credential the resolved settings need (today: the proxy password)."""
    # credentials/ is dropped at generation time when include_auth=false;
    # detecting it at runtime keeps this file free of template logic.
    if importlib.util.find_spec(f"{_PACKAGE_NAME}.credentials") is None:
        return []
    credentials = importlib.import_module(f"{_PACKAGE_NAME}.credentials.manager")

    backend = credentials.store_backend()
    checks: list[dict] = [
        {
            "name": "credential_store",
            "ok": backend is not None,
            "detail": backend or "no usable OS keychain backend; credentials must come from environment variables",
        }
    ]
    for provider in needed:
        available = credentials.get_credential(provider) is not None
        checks.append(
            {
                "name": f"credential:{provider}",
                "ok": available,
                "detail": "" if available else f"run '{cli_name()} auth login --provider {provider}'",
            }
        )
    return checks


def _settings_check(root: Path | None, config: ProjectConfig | None) -> tuple[dict, list[str]]:
    """Resolve the crawl settings like `spider crawl` would; returns the check and the credentials they need."""
    try:
        data = services.read_project_data(root) if root and config else None
        crawl = settings.resolve(root, project_data=data).settings.crawl
    except CliError as exc:
        return {"name": "settings", "ok": False, "detail": exc.message}, []
    needed = [crawl_service.PROXY_CREDENTIAL] if any("{password}" in u for u in crawl.proxy_urls) else []
    if crawl.auth == "basic":
        needed.append(crawl_service.SITE_CREDENTIAL)
    return {"name": "settings", "ok": True}, needed


@output.guard
def doctor(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Проверить окружение: Python, версию CLI, проект, конфиг и настройки, базу обходов, секреты.

    Первое, что стоит запустить, если команда ведёт себя странно. Код выхода
    всегда 0 — результат это сам отчёт; `healthy` говорит, прошли ли все проверки.
    `database` — путь к базе обходов (`SPIDER_DB_PATH` переопределяет) или, с
    `SPIDER_DB_URL`, сервер PostgreSQL — отвечает ли он и есть ли пароль; `settings` —
    настройки обхода собираются без ошибок; `credential:proxy` — есть пароль прокси,
    если `crawl.proxy_urls` его требует (`{password}`); `credential:site` — пароль сайта
    при `crawl.auth = basic`; `lighthouse` — найдена ли команда Lighthouse
    (`lighthouse.command`; нужна только для `spider lighthouse`, на healthy не влияет), а при
    `lighthouse.source = psi` — установлен ли gsc и есть ли у него ключ PageSpeed Insights.

    Примеры:
      spider doctor
      spider --json doctor

    JSON: `{healthy, checks: [{name, ok, detail}]}`.
    """
    checks: list[dict] = [{"name": "python", "ok": True}]
    checks.append({"name": "cli_version", "ok": True, "detail": installed_version() or DEV_VERSION})

    start = Path(ctx.obj.get("project") or Path.cwd())
    output.vecho(ctx, f"Searching for a project root starting at: {start}")
    root = services.find_project_root(start)
    checks.append({"name": "project", "ok": root is not None, "detail": str(root) if root else None})

    config: ProjectConfig | None = None
    if root is not None:
        try:
            config = services.load_config(root, check_compat=False)
            checks.append({"name": "config", "ok": True})
        except Exception as exc:
            checks.append({"name": "config", "ok": False, "detail": str(exc)})
    if config is not None:
        try:
            services.check_cli_compat(config)
            checks.append({"name": "cli_compat", "ok": True, "detail": f"project requires >= {config.cli.min_version}"})
        except CliTooOld as exc:
            checks.append({"name": "cli_compat", "ok": False, "detail": exc.message})

    checks.append(_database_check())

    settings_check, needed = _settings_check(root, config)
    checks.append(settings_check)
    checks.extend(_auth_checks(needed))
    checks.append(_lighthouse_check(root, config))

    all_ok = all(check["ok"] for check in checks)
    output.emit_success(
        ctx, {"healthy": all_ok, "checks": checks}, render_human=lambda data: output.human.render_doctor(data["checks"])
    )


def _database_check() -> dict:
    """The local SQLite file, or (SPIDER_DB_URL) whether the PostgreSQL server answers with the password it has."""
    url = storage.db_url()
    if url is None:
        database = storage.db_path()
        return {"name": "database", "ok": True,
                "detail": f"{database}" + ("" if database.exists() else " (создастся при первом обходе)")}  # fmt: skip
    from ..core.errors import CliError

    try:
        shown = storage.remote_url(url).render_as_string(hide_password=True)
        storage.open_db_url(url).dispose()
    except CliError as exc:
        return {"name": "database", "ok": False, "detail": f"{exc.message} {exc.action or ''}".strip()}
    return {"name": "database", "ok": True, "detail": f"PostgreSQL {shown}"}


def _lighthouse_check(root: Path | None, config: ProjectConfig | None) -> dict:
    """Lighthouse for `spider lighthouse`: optional — its absence doesn't make the environment unhealthy."""
    from ..core import lighthouse

    try:
        data = services.read_project_data(root) if root and config else None
        lh = settings.resolve(root, project_data=data).settings.lighthouse
    except CliError:  # broken settings are the settings check's to report
        return {"name": "lighthouse", "ok": True, "detail": "не проверялось: настройки не собрались"}
    if lh.source == "psi":
        return _pagespeed_check()
    found = lighthouse.available(lh)
    detail = (
        f"{lh.command} → {found}"
        if found
        else (f"не найден ({lh.command}) — нужен только для `spider lighthouse`: npm install -g lighthouse")
    )
    return {"name": "lighthouse", "ok": True, "detail": detail}


def _pagespeed_check() -> dict:
    """PageSpeed Insights for `spider lighthouse --source psi`: the gsc package and its key (keychain / env)."""
    try:
        import gsc
    except ImportError:
        return {"name": "lighthouse", "ok": True, "detail": "source = psi, но gsc не установлен: uv sync --extra gsc"}
    try:
        has_key = gsc.auth_status().pagespeed_key
    except gsc.CliError as exc:
        return {"name": "lighthouse", "ok": True, "detail": f"source = psi, gsc {gsc.__version__}: {exc.message}"}
    detail = "ключ есть" if has_key else "ключа нет — gsc auth login --provider pagespeed"
    return {"name": "lighthouse", "ok": True, "detail": f"source = psi, gsc {gsc.__version__}: {detail}"}
