from __future__ import annotations

import dataclasses

import typer

from .. import output
from ..core import maintenance, storage

app = output.group("База обходов: размер и состояние, миграции схемы, сжатие файла.")


@app.command("info")
@output.guard
def info(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать базу обходов: где лежит, сколько весит, версия схемы, сколько данных.

    «Свободно внутри» — место удалённых обходов, которое займут следующие обходы
    или вернёт на диск `spider db vacuum`. Схема не обновляется этой командой:
    если ждут миграции, их видно здесь (применяет `spider db migrate` или любая
    другая команда).

    Примеры:
      spider db info
      spider --json db info

    JSON: `{path, size_bytes, html_path, html_size_bytes, free_bytes, sqlite_version,
    schema_revision, schema_head, pending_migrations, projects, crawls, pages, links, issues}`.
    """
    with storage.database(migrate=False) as engine:
        data = dataclasses.asdict(maintenance.db_info(engine))
    output.emit_success(ctx, data, render_human=output.human.db_info)


@app.command("migrate")
@output.guard
def migrate(
    ctx: typer.Context,
    dry_run: bool = output.DryRunOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Обновить схему базы до версии этого spider (миграции Alembic).

    Обычно не нужна: любая команда сама применяет недостающие миграции при
    открытии базы. Полезна, чтобы обновить схему явно (после обновления spider,
    перед долгим фоновым обходом) или посмотреть с `--dry-run`, что изменится.

    Примеры:
      spider db migrate --dry-run
      spider db migrate

    JSON: `{migrations: [ревизия, ...], schema_head, dry_run}`; `migrations` —
    применённые (или, с `--dry-run`, ожидающие), пусто — схема актуальна.
    """
    with storage.database(migrate=False) as engine:
        info = maintenance.db_info(engine)
        applied = info.pending_migrations if output.is_dry_run(ctx) else maintenance.migrate(engine)
    data = {"migrations": applied, "schema_head": info.schema_head, "dry_run": output.is_dry_run(ctx)}
    output.emit_success(ctx, data, render_human=output.human.migrations)


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

    Примеры:
      spider db vacuum
      spider --json db vacuum

    JSON: `{before_bytes, after_bytes}` — размер файлов баз до и после. База
    занята идущим обходом — выход 2.
    """
    with storage.database() as engine:
        before, after = maintenance.vacuum(engine)
    output.emit_success(ctx, {"before_bytes": before, "after_bytes": after}, render_human=output.human.vacuumed)
