from __future__ import annotations

import importlib
from pathlib import Path

import typer

from .. import output
from ..core import crawl as crawl_service
from ..core import deps, services, settings
from ..core import proxy as proxy_service
from ..core.errors import CliError, CliTooOld
from ..core.models import ProjectConfig
from ..core.version import DEV_VERSION, cli_name, installed_version, module_exists
from ..providers import secrets

_PACKAGE_NAME = __name__.split(".")[0]


def _auth_checks(needed: list[str]) -> list[dict]:
    """The keychain, plus every credential the resolved settings need (the proxy password and change-IP key, the site's password)."""
    # credentials/ is dropped at generation time when include_auth=false;
    # detecting it at runtime keeps this file free of template logic.
    if not module_exists(f"{_PACKAGE_NAME}.credentials.manager"):
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
        available = secrets.password(provider) is not None
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
    needed = [proxy_service.PROXY_CREDENTIAL] if any("{password}" in u for u in crawl.proxy_urls) else []
    if any("{key}" in u for u in crawl.proxy_change_ip_urls):
        needed.append(proxy_service.KEY_CREDENTIAL)
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
    `SPIDER_DATABASE_URL`, сервер PostgreSQL — отвечает ли он и есть ли пароль;
    `database_schema` — схема базы на версии этого spider (иначе — `spider db upgrade`);
    `database_env` — задано устаревшее `SPIDER_DB_URL` (переименовать); `settings` —
    настройки обхода собираются без ошибок; `credential:proxy` — есть пароль прокси,
    если `crawl.proxy_urls` его требует (`{password}`); `credential:proxy_key` — ключ смены
    IP, если его требует `crawl.proxy_change_ip_urls` (`{key}`); `credential:site` — пароль сайта
    при `crawl.auth = basic`; `lighthouse` — найдена ли команда Lighthouse
    (`lighthouse.command`; нужна только для `spider lighthouse`, на healthy не влияет), а при
    `lighthouse.source = psi` — установлен ли gsc и есть ли у него ключ PageSpeed Insights;
    `external:<программа>` — внешние программы из `[[tool.rb.external]]` (`lighthouse`, `npx`):
    версия или «не установлена»; все необязательные, на healthy не влияют. Пароли ищутся и в
    keychain `rb_spider:<провайдер>`, где их хранил spider до 0.2.0.

    Example: spider doctor
    Example: spider --json doctor

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

    settings_check, needed = _settings_check(root, config)
    checks.append(settings_check)
    checks.extend(_auth_checks(needed))
    checks.append(_lighthouse_check(root, config))
    checks.extend(deps.doctor_checks())  # [[tool.rb.external]] in pyproject.toml
    if module_exists(f"{_PACKAGE_NAME}.core.db"):  # include_db=false drops it at generation time
        checks.extend(importlib.import_module(f"{_PACKAGE_NAME}.core.db").doctor_checks())

    all_ok = all(check["ok"] for check in checks)
    output.emit_success(
        ctx, {"healthy": all_ok, "checks": checks}, render_human=lambda data: output.human.render_doctor(data["checks"])
    )


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
