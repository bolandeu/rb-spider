from __future__ import annotations

import typer

from .. import output
from ..core import crawl as crawl_service
from ..core import maintenance, storage
from ..core.errors import InvalidArguments
from . import options

app = output.group("Обходы в базе: список, просмотр, продолжение прерванного, удаление и чистка старых.")


@app.command("list")
@output.guard
def list_crawls(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit", min=1, help="Сколько последних обходов показать."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать обходы всех проектов, новые сверху.

    Примеры:
      spider crawls list
      spider --json crawls list --limit 5

    JSON: `{crawls: [{id, project, start_url, status, started_at, finished_at, pages}]}`,
    даты — ISO 8601 в UTC; `status` — running | finished | failed | interrupted.
    """
    with storage.database() as engine:
        rows = storage.list_crawls(engine, limit=limit)
    data = {
        "crawls": [
            {
                **vars(row),
                "started_at": row.started_at.isoformat(),
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in rows
        ]
    }
    output.emit_success(ctx, data, render_human=lambda d: output.human.crawls_table(d["crawls"]))


@app.command("show")
@output.guard
def show_crawl(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода; по умолчанию — последний."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать обход и настройки, с которыми он шёл.

    Снимок настроек объясняет, почему два обхода одного сайта различаются
    (другой профиль, лимит, User-Agent).

    Примеры:
      spider crawls show
      spider --json crawls show 12

    JSON: `{id, project, start_url, status, started_at, finished_at, pages, settings}`;
    `settings` — null у обходов, сделанных до появления снимков. Нет обхода — выход 2.
    """
    with storage.database() as engine:
        row, snapshot = storage.get_crawl(engine, storage.resolve_crawl_id(engine, crawl_id))
    data = {
        **vars(row),
        "started_at": row.started_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "settings": snapshot,
    }
    output.emit_success(ctx, data, render_human=output.human.crawl_details)


@app.command("resume")
@output.guard
def resume(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода; по умолчанию — последний."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Продолжить прерванный обход с того места, где он остановился.

    После Ctrl-C, падения, перезагрузки или `kill -9`: очередь восстанавливается из
    базы, уже сохранённые URL заново не скачиваются, потерянных нет. Настройки — те,
    с которыми обход начинался (`spider crawls show`). Так же запускается обход
    в фоне (`spider crawl --detach`).

    Примеры:
      spider crawls resume
      spider --json crawls resume 12

    JSON — как у `spider crawl`: `{crawl_id, project, start_url, status, pages, elapsed_s}`.
    Обход уже завершён или ещё идёт — выход 2.
    """

    def progress(pages: int) -> None:
        if not (ctx.obj.get("json") or json_output or ctx.obj.get("quiet") or quiet):
            output.human.err_console.print(f"… {pages} URL")

    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        crawl_service.ensure_resumable(engine, crawl_id)
        result = crawl_service.run_crawl(engine, crawl_id, on_progress=progress)
    output.emit_success(ctx, vars(result), render_human=output.human.crawl_result)


@app.command("respider")
@output.guard
def respider(
    ctx: typer.Context,
    crawl_id: int = typer.Argument(..., help="Номер обхода (`spider crawls list`)."),
    urls: list[str] | None = typer.Argument(None, help="URL обхода, которые скачать заново."),
    url_list: str | None = typer.Option(
        None, "--list", help="Файл с URL (как у `spider crawl --list`) или - для stdin."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Переобойти выбранные URL обхода: скачать заново, заменить их данные и ссылки, пересчитать проверки.

    После исправлений на нескольких страницах — чтобы не обходить сайт целиком. URL
    должны быть в обходе; новые ссылки с них записываются, но не обходятся. Настройки —
    те, с которыми обход шёл. Сравнить до и после целиком — `spider compare`.

    Примеры:
      spider crawls respider 12 https://example.com/ https://example.com/catalog/
      spider crawls respider 12 --list fixed.txt

    JSON — как у `spider crawl`: `{crawl_id, project, start_url, status, pages, elapsed_s}`.
    URL нет в обходе, нет ни URL, ни `--list`, обход ещё идёт — выход 2.
    """
    targets = list(urls or [])
    if url_list is not None:
        targets += crawl_service.read_url_list(options.read_url_source(url_list))
    if not targets:
        raise InvalidArguments("Give the URLs to re-spider, or --list <file>.")
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        result = crawl_service.respider(engine, crawl_id, targets)
    output.emit_success(ctx, vars(result), render_human=output.human.crawl_result)


def _deletion(ctx: typer.Context, engine, rows: list[storage.CrawlRow], confirm: bool) -> dict:
    """Delete (or, under --dry-run, only list) crawls; the JSON both commands print."""
    data = {"crawls": [{"id": r.id, "project": r.project, "start_url": r.start_url, "pages": r.pages} for r in rows],
            "pages": sum(r.pages for r in rows), "dry_run": output.is_dry_run(ctx)}  # fmt: skip
    if rows and not data["dry_run"]:
        output.require_confirmation(ctx, f"Delete {len(rows)} crawl(s) with {data['pages']} pages", confirm)
        maintenance.delete_crawls(engine, rows)
    return data


@app.command("delete")
@output.guard
def delete(
    ctx: typer.Context,
    crawl_ids: list[int] = typer.Argument(..., help="Номера обходов (`spider crawls list`)."),
    dry_run: bool = output.DryRunOption,
    confirm: bool = output.ConfirmOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    non_interactive: bool = output.NonInteractiveOption,
) -> None:
    """Удалить обходы со всеми их данными: страницами, ссылками, находками, HTML.

    Необратимо: спрашивает подтверждение; `--yes` — без вопроса (агентам),
    `--dry-run` — только показать, что удалится. Идущий обход не удаляется.
    Место внутри файла базы сразу переиспользуется следующими обходами, а на
    диск его возвращает `spider db vacuum`. Чистка по возрасту и количеству —
    `spider crawls prune`, проект целиком — `spider projects delete`.

    Примеры:
      spider crawls delete 3 4 --dry-run
      spider crawls delete 3
      spider --json crawls delete 3 --yes

    JSON: `{crawls: [{id, project, start_url, pages}], pages, dry_run}`. Нет
    такого обхода или он ещё идёт — выход 2; отказ в подтверждении — выход 1.
    """
    with storage.database() as engine:
        data = _deletion(ctx, engine, maintenance.select_crawls(engine, crawl_ids), confirm)
    output.emit_success(ctx, data, render_human=output.human.deletion)


@app.command("prune")
@output.guard
def prune(
    ctx: typer.Context,
    keep_last: int | None = typer.Option(
        None, "--keep-last", min=0, help="Оставить столько последних обходов каждого проекта, остальные удалить."
    ),
    older_than: str | None = typer.Option(None, "--older-than", help="Удалить обходы старше этого: 90d, 12h, 2w, 1y."),
    project: str | None = typer.Option(
        None, "--project-name", help="Только обходы этого проекта; по умолчанию — всех."
    ),
    dry_run: bool = output.DryRunOption,
    confirm: bool = output.ConfirmOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    non_interactive: bool = output.NonInteractiveOption,
) -> None:
    """Удалить старые обходы: сверх N последних в каждом проекте и/или старше срока.

    Чтобы база не росла бесконечно (обход 100k URL — около 800 МБ). С обоими
    условиями удаляется обход, который и старше срока, и не входит в N последних
    своего проекта. Подтверждение, `--yes` и `--dry-run` — как у `crawls delete`.

    Примеры:
      spider crawls prune --keep-last 3 --dry-run
      spider crawls prune --older-than 90d
      spider --json crawls prune --keep-last 5 --older-than 30d --project-name shop --yes

    JSON — как у `crawls delete`: `{crawls: [{id, project, start_url, pages}], pages,
    dry_run}`. Не задано ни одно условие или неверный срок — выход 2.
    """
    age = maintenance.parse_age(older_than) if older_than is not None else None
    with storage.database() as engine:
        rows = maintenance.select_prune(engine, keep_last=keep_last, older_than=age, project=project)
        data = _deletion(ctx, engine, rows, confirm)
    output.emit_success(ctx, data, render_human=output.human.deletion)
