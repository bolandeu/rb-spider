from __future__ import annotations

import json
import shutil
from pathlib import Path

import typer

from .. import output
from ..core import fingerprint
from ..core.errors import InvalidArguments
from . import options

app = output.group("Отпечатки браузера из файлов (crawl.fingerprint): один на весь обход, вместе с прокси.")


@app.command("list")
@output.guard
def list_fingerprints(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать отпечатки в папке пользователя — их имена для `crawl.fingerprint`.

    Папка общая для всех проектов: `~/.config/spider/fingerprints/` на Linux,
    `~/Library/Application Support/spider/fingerprints/` на macOS. Положить файл —
    `spider fingerprints add`.

    Example: spider fingerprints list

    JSON: `{folder, fingerprints: [{name, path, user_agent, ip}]}`; битый файл — с `error`.
    """
    rows = []
    for name, path in fingerprint.available().items():
        try:
            found = fingerprint.load(str(path))
            rows.append({"name": name, "path": str(path), "user_agent": found.navigator.userAgent, "ip": found.ip})
        except InvalidArguments as exc:
            rows.append({"name": name, "path": str(path), "error": exc.message})
    data = {"folder": str(fingerprint.fingerprints_dir()), "fingerprints": rows}
    output.emit_success(ctx, data, render_human=output.human.fingerprints_table)


@app.command("add")
@output.guard
def add_fingerprint(
    ctx: typer.Context,
    source: Path = typer.Argument(..., help="JSON-файл отпечатка (выгрузка сервиса отпечатков)."),
    name: str | None = typer.Option(None, "--name", help="Имя для crawl.fingerprint; по умолчанию — имя файла."),
    force: bool = typer.Option(False, "--force", help="Заменить отпечаток с тем же именем."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Положить файл отпечатка в папку пользователя, проверив, что spider его читает.

    Удобно называть отпечаток так же, как прокси, с которым он работает. Заменить
    отпечаток — `add --force` с тем же именем; удалить — удалить файл из папки
    (`spider fingerprints list` её показывает).

    Example: spider fingerprints add ~/Downloads/fp.json --name mp-123
    Example: spider fingerprints add new.json --name mp-123 --force

    JSON: `{name, path}`. Файл не читается как отпечаток или имя занято (без
    `--force`) — выход 2.
    """
    fingerprint.load(str(source.expanduser()))  # a fingerprint spider can read, or exit 2 now
    target = fingerprint.fingerprints_dir() / f"{name or source.stem}.json"
    if target.exists() and not force:
        raise InvalidArguments(f"Fingerprint '{target.stem}' already exists: {target} (use --force to replace it).")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source.expanduser(), target)
    output.emit_success(
        ctx,
        {"name": target.stem, "path": str(target)},
        render_human=lambda d: output.human.echo(f"Отпечаток {d['name']}: {d['path']}"),
    )


@app.command("new")
@output.guard
def new_fingerprint(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Имя нового отпечатка для crawl.fingerprint."),
    os: str = typer.Option("windows", "--os", help="Система: windows, macos, linux или android (телефон)."),
    chrome: int | None = typer.Option(
        None, "--chrome", min=100, help="Версия Chrome (major), например 155; по умолчанию — из данных генератора."
    ),
    locale: str = typer.Option("ru-RU", "--locale", help="Язык браузера (navigator.language, Accept-Language)."),
    timezone: str = typer.Option("Europe/Moscow", "--timezone", help="Часовой пояс браузера (IANA)."),
    force: bool = typer.Option(False, "--force", help="Заменить отпечаток с тем же именем."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сгенерировать отпечаток и сохранить его в папку пользователя — вместо файла сервиса.

    Генератор browserforge (тот же, что у Crawlee) собирает сочетание железа,
    экрана, видеокарты и шрифтов из статистики реальных браузеров. Его данные
    отстают от релизов Chrome — задайте актуальную версию `--chrome`: User-Agent,
    sec-ch-ua (с «GREASE»-брендом, как у настоящего Chrome) и client hints пойдут
    под неё. Отпечаток сохраняется файлом, поэтому одинаков во всех обходах, пока
    его не заменить. Нужен `rb-spider[render]`. Часовой пояс и язык — как у IP прокси;
    у мобильного прокси естественнее всего `--os android` (IP оператора — телефон).

    Example: spider fingerprints new mp-123 --os windows --chrome 155
    Example: spider fingerprints new mac-1 --os macos --chrome 155 --locale ru-RU
    Example: spider fingerprints new phone-1 --os android --chrome 155

    JSON: `{name, path, user_agent}`. Имя занято (без `--force`) или неизвестная
    `--os` — выход 2; без `rb-spider[render]` — выход 1, `RENDER_UNAVAILABLE`.
    """
    if os not in ("windows", "macos", "linux", "android"):
        raise InvalidArguments(f"--os: windows, macos, linux or android, not '{os}'.")
    from ..core.render import ensure_available

    ensure_available()  # browserforge comes with Crawlee's Playwright extra
    target = fingerprint.fingerprints_dir() / f"{name}.json"
    if target.exists() and not force:
        raise InvalidArguments(f"Fingerprint '{name}' already exists: {target} (use --force to replace it).")
    data = fingerprint.generate(os, chrome, locale, timezone)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    fingerprint.load(str(target))  # what was written reads back
    output.emit_success(
        ctx,
        {"name": name, "path": str(target), "user_agent": data["navigator"]["userAgent"]},
        render_human=lambda d: output.human.echo(f"Отпечаток {d['name']}: {d['path']}\n  {d['user_agent']}"),
    )


@app.command("check")
@output.guard
def check_fingerprint(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Имя из `spider fingerprints list` или путь к файлу."),
    profile: str | None = options.ProfileOption,
    config_file: Path | None = options.ConfigFileOption,
    assignments: list[str] | None = options.SetOption,
    render: bool = typer.Option(False, "--render", help="Сверить и с ОС этой машины — для обхода с рендерингом."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сверить отпечаток: одна ли в нём ОС и совпадает ли он со страной и часовым поясом выходного IP.

    То же, что обход делает перед стартом (`crawl.fingerprint_check`), но без обхода:
    User-Agent, platform, client hints, видеокарта, шрифты и TCP-отпечаток прокси
    (`_meta.tcp_match`, выставляется у провайдера) должны говорить об одной ОС; с
    `--render` — ещё и совпадать с ОС этой машины (шрифты и canvas браузера — её).
    Выходной IP — через прокси из `--profile` (или напрямую, без прокси): страна и
    часовой пояс по ipinfo.io против часового пояса и языка отпечатка. С
    `crawl.fingerprint_timezone = ip` (по умолчанию) часовой пояс браузера и так
    берётся у IP — расходиться могут только страна и язык.

    Example: spider fingerprints check mp-123 --profile mobile-proxy
    Example: spider fingerprints check mac-1 --profile mobile-proxy --render

    JSON: `{ok, issues, exit_ip: {ip, country, timezone} | null}`; `ok` — расхождений нет.
    Код выхода 0 и при расхождениях — результат в `ok`/`issues`; нет файла — 2; прокси
    не работает — 5, `PROXY_UNAVAILABLE`.
    """
    import asyncio

    from ..core.crawl import http_client
    from ..core.proxy import open_proxies

    crawl = options.resolve(ctx, profile, config_file, assignments).settings.crawl
    found = fingerprint.load(name)

    async def run() -> dict:
        client = http_client(crawl)
        proxies, _ = await open_proxies(
            crawl.model_copy(update={"proxy_fallback": "stop"}), client, fingerprint.GEO_URL
        )
        geo = await fingerprint.exit_geo(client, await proxies.exit_proxy() if proxies else None, crawl.timeout_s)
        checked = found
        if geo and geo.get("timezone") and crawl.fingerprint_timezone == "ip":
            checked = fingerprint.with_timezone(found, str(geo["timezone"]))  # what a crawl would use
        issues = fingerprint.os_issues(checked, render=render) + (fingerprint.geo_issues(checked, geo) if geo else [])
        exit_ip = {k: geo.get(k) for k in ("ip", "country", "timezone")} if geo else None
        return {"ok": not issues, "issues": issues, "exit_ip": exit_ip}

    output.emit_success(ctx, asyncio.run(run()), render_human=output.human.fingerprint_check)


@app.command("show")
@output.guard
def show_fingerprint(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Имя из `spider fingerprints list` или путь к файлу."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать, что отпечаток задаёт: заголовки всех запросов и что видит сайт в браузере.

    Заголовки (User-Agent, Accept-Language, sec-ch-ua*) идут с каждым запросом
    обхода; остальное — в браузере рендеринга (`crawl.render`), через скрипт
    browserforge, как у Crawlee. Не подделываются: canvas, audio, шрифты и
    TLS-отпечаток обычных запросов (у impit свой Chrome) — `not_faked`.

    Example: spider fingerprints show mp-123

    JSON: `{path, ip, headers, browser: {platform, languages, hardware_concurrency,
    device_memory, screen, webgl, timezone, locale, webrtc}, not_faked}`. Нет
    файла или он не читается — выход 2.
    """
    found = fingerprint.load(name)
    path = fingerprint.fingerprint_path(name)
    output.emit_success(ctx, fingerprint.summary(found, path), render_human=output.human.fingerprint_view)
