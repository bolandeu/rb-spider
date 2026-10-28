"""The `doctor` command: checks of this CLI's own setup, one line per check."""

from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import crawl as crawl_service
from ..core import deps, proxy_state, services, settings
from ..core import proxy as proxy_service
from ..core.errors import CliError
from ..core.models import ProjectConfig
from ..core.version import DEV_VERSION, cli_name, installed_version, optional_module
from ..providers import secrets

_PACKAGE_NAME = __name__.split(".")[0]


def _auth_checks(needed: list[str]) -> list[dict]:
    """Every credential the resolved settings need (the proxy password and change-IP key, the site's password)."""
    return [
        {
            "name": f"credential:{provider}",
            "ok": secrets.password(provider) is not None,
            "detail": ""
            if secrets.password(provider) is not None
            else f"run '{cli_name()} auth login --provider {provider}'",
        }
        for provider in needed
    ]


def _proxy_check(crawl: settings.CrawlSettings) -> list[dict]:
    """The remembered state of each `crawl.proxy_urls` address (core/proxy_state.py), no network: dead → not ok."""
    if not crawl.proxy_urls:
        return []
    addresses = []
    for url in crawl.proxy_urls:
        found = proxy_state.entry(url) or {}
        addresses.append({"address": proxy_state.display_address(url), "state": found.get("status") or "unknown",
                          "checked_at": found.get("checked_at"), "reason": found.get("reason"),
                          "ip_changes_24h": len(found.get("ip_changes", []))})  # fmt: skip
    lines = [f"{a['address']}: {a['state']}" + (f", {a['checked_at']}" if a["checked_at"] else "")
             + (f", {a['reason']}" if a["reason"] else "") + f", IP changes in 24 h: {a['ip_changes_24h']}"
             for a in addresses]  # fmt: skip
    detail = f"{'; '.join(lines)}. Check now: {cli_name()} auth status --check"
    return [{"name": "proxy", "ok": all(a["state"] != "dead" for a in addresses), "detail": detail,
             "addresses": addresses}]  # fmt: skip


def _settings_check(root: Path | None, config: ProjectConfig | None) -> tuple[dict, list[str], list[dict]]:
    """Resolve the crawl settings like `spider crawl` would; returns the check, the credentials they need and the
    proxy checks."""
    try:
        data = services.read_project_data(root) if root and config else None
        crawl = settings.resolve(root, project_data=data).settings.crawl
    except CliError as exc:
        return {"name": "settings", "ok": False, "detail": exc.message}, [], []
    needed = [proxy_service.PROXY_CREDENTIAL] if any("{password}" in u for u in crawl.proxy_urls) else []
    if any("{key}" in u for u in crawl.proxy_change_ip_urls):
        needed.append(proxy_service.KEY_CREDENTIAL)
    if crawl.auth == "basic":
        needed.append(crawl_service.SITE_CREDENTIAL)
    return {"name": "settings", "ok": True}, needed, _proxy_check(crawl)


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
    если `crawl.proxy_urls` его требует (`{password}`); `proxy` — если задан `crawl.proxy_urls`: каждый адрес
    (без пароля) с запомненным состоянием (`alive`, `dead` или `unknown`), временем проверки, причиной и числом смен
    IP за 24 ч, в `addresses[]`; читается из файла состояния, без сети, мёртвый адрес — не ok; проверить сейчас —
    `spider auth status --check`; `credential:proxy_key` — ключ смены
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

    if project := optional_module(f"{_PACKAGE_NAME}.commands.project"):  # include_project=false drops it
        checks.extend(project.doctor_checks(ctx))

    root = services.find_project_root(Path(ctx.obj.get("project") or Path.cwd()))
    config: ProjectConfig | None = None
    if root is not None:
        try:
            config = services.load_config(root, check_compat=False)
        except Exception:  # reported by the project part's `config` check
            config = None
    settings_check, needed, proxy_checks = _settings_check(root, config)
    checks.append(settings_check)
    if credentials := optional_module(f"{_PACKAGE_NAME}.credentials.health"):  # include_auth=false drops it
        checks.extend(credentials.doctor_checks())
    checks.extend(_auth_checks(needed))
    checks.extend(proxy_checks)
    checks.append(_lighthouse_check(root, config))
    checks.extend(deps.doctor_checks())  # [[tool.rb.external]] in pyproject.toml
    if db := optional_module(f"{_PACKAGE_NAME}.core.db"):  # include_db=false drops it at generation time
        checks.extend(db.doctor_checks())

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
