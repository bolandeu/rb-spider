from __future__ import annotations

import dataclasses
from pathlib import Path

import typer

from .. import output
from ..core import db, maintenance, storage

app = output.group("База обходов: размер и состояние, миграции схемы, перенос в общую базу, сжатие файла.")


@app.command("info")
@output.guard
def info(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать базу обходов: где лежит, сколько весит, версия схемы, сколько данных.

    По умолчанию база — файл SQLite в папке данных (`SPIDER_DB_PATH` — другой
    путь). `SPIDER_DATABASE_URL=postgresql://пользователь@хост:5432/база` — общая база
    PostgreSQL (на сервере); пароль — в URL или в keychain: `spider auth login
    --provider database`. Старое имя `SPIDER_DB_URL` пока читается, с предупреждением.
    Сохранённый HTML и тогда лежит локальным файлом, отдельным для каждой базы.
    Таблицы spider — `spider_*`; размер у PostgreSQL — только их.

    «Свободно внутри» — место удалённых обходов, которое займут следующие обходы
    или вернёт на диск `spider db vacuum` (у PostgreSQL — 0). Схема не обновляется
    этой командой: если ждут миграции, их видно здесь (применяет `spider db
    upgrade`; SQLite — и любая другая команда).

    Example: spider db info
    Example: spider --json db info

    JSON: `{path, size_bytes, html_path, html_size_bytes, free_bytes, sqlite_version,
    schema_revision, schema_head, pending_migrations, projects, crawls, pages, links, issues,
    engine, server_version}`; engine — sqlite | postgresql, path у PostgreSQL — URL без
    пароля, server_version — версия сервера PostgreSQL.
    """
    with storage.database(migrate=False) as engine:
        data = dataclasses.asdict(maintenance.db_info(engine))
    output.emit_success(ctx, data, render_human=output.human.db_info)


def _upgrade(ctx: typer.Context) -> None:
    with storage.database(migrate=False) as engine:
        info = maintenance.db_info(engine)
        applied = info.pending_migrations if output.is_dry_run(ctx) else maintenance.migrate(engine)
    data = {"migrations": applied, "schema_head": info.schema_head, "dry_run": output.is_dry_run(ctx)}
    output.emit_success(ctx, data, render_human=output.human.migrations)


@app.command("upgrade")
@output.guard
def upgrade(
    ctx: typer.Context,
    dry_run: bool = output.DryRunOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Обновить схему базы до версии этого spider (миграции Alembic).

    Общая база PostgreSQL (`SPIDER_DATABASE_URL`) сама не мигрирует никогда: после
    обновления spider, принёсшего миграции, её обновляет эта команда, запущенная из
    релизной версии (два запуска сразу ждут друг друга). Пока схема отстаёт,
    остальные команды отвечают `DATABASE_NOT_MIGRATED`. Новая пустая база получает
    всю схему сразу. Локальный файл SQLite мигрирует и сам, при любом открытии.

    Example: spider db upgrade --dry-run
    Example: spider db upgrade

    JSON: `{migrations: [ревизия, ...], schema_head, dry_run}`; `migrations` —
    применённые (или, с `--dry-run`, ожидающие), пусто — схема актуальна.
    """
    _upgrade(ctx)


@app.command("migrate", hidden=True, deprecated=True)
@output.guard
def migrate(
    ctx: typer.Context,
    dry_run: bool = output.DryRunOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Старое имя `spider db upgrade` (до 0.3); будет убрано.

    Example: spider db migrate --dry-run
    """
    _upgrade(ctx)


@app.command("import-sqlite")
@output.guard
def import_sqlite(
    ctx: typer.Context,
    path: Path = typer.Argument(None, help="Файл SQLite, который перенести; по умолчанию — локальная база spider."),
    dry_run: bool = output.DryRunOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Перенести обходы из файла SQLite в базу из `SPIDER_DATABASE_URL`, разово.

    Для переезда на общую базу PostgreSQL: задать `SPIDER_DATABASE_URL`, обновить
    схему (`spider db upgrade`), затем запустить эту команду. Файл сначала
    мигрирует до версии этого spider (даже с `--dry-run`). Все таблицы в целевой
    базе должны быть пустыми — это переезд, не слияние; все строки идут одной
    транзакцией. `--dry-run` считает строки и ничего не пишет.

    Example: spider db import-sqlite --dry-run
    Example: spider db import-sqlite ~/old/spider.sqlite

    JSON: `{source, dry_run, rows: {таблица: строк}}`. Таблица в целевой базе не
    пуста — выход 2.
    """
    source = path or db.sqlite_path()
    with storage.database() as engine:
        counts = db.import_sqlite(source, engine, dry_run=output.is_dry_run(ctx))
    output.emit_success(
        ctx,
        {"source": str(source), "dry_run": output.is_dry_run(ctx), "rows": counts},
        render_human=lambda d: output.human.key_values(
            ("Будет перенесено" if d["dry_run"] else "Перенесено") + f" из {d['source']}", d["rows"]
        ),
    )


@app.command("vacuum")
@output.guard
def vacuum(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сжать файл базы (и базы HTML): вернуть на диск место удалённых обходов.

    После `spider crawls delete|prune` и `spider projects delete` файл не
    уменьшается — освободившееся место переиспользуют следующие обходы. VACUUM
    переписывает файл заново: нужно свободное место на диске размером с базу, а
    во время работы обходы не должны идти. Сколько вернётся — `spider db info`.
    PostgreSQL (`SPIDER_DATABASE_URL`) — VACUUM FULL только таблиц spider: они
    переписываются и на это время заблокированы.

    Example: spider db vacuum
    Example: spider --json db vacuum

    JSON: `{before_bytes, after_bytes}` — размер файлов баз (у PostgreSQL — таблиц
    spider) до и после. База занята идущим обходом — выход 2.
    """
    with storage.database() as engine:
        before, after = maintenance.vacuum(engine)
    output.emit_success(ctx, {"before_bytes": before, "after_bytes": after}, render_human=output.human.vacuumed)
