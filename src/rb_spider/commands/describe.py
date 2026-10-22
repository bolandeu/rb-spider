"""The `describe` command: the machine-readable description (OpenCLI document) of this CLI for agents."""

from __future__ import annotations

import json

import typer

from .. import output
from ..core import opencli


@output.guard
def describe(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Напечатать машиночитаемый контракт spider — документ OpenCLI (opencli.org).

    Для каталога инструментов, Windmill и агентов: всё, что раньше собиралось из
    `--help` каждой команды, одним документом. Человеку удобнее `spider --help`.

    Внутри: команды, опции, аргументы, коды выхода и метаданные `x-rb-*` —
    переменные окружения, таблицы, представления `spider_v1_*` с колонками,
    файлы в папке данных, внешние программы, версия шаблона.

    Example: {cli} describe --json
    Example: {cli} describe

    Выход: с --json — голый документ одной строкой (без обёртки {"ok": ...}),
    ключи верхнего уровня `opencli`, `info`, `command`; без --json — тот же
    документ с отступами.
    """
    document = opencli.document(ctx.find_root().command)
    typer.echo(json.dumps(document, ensure_ascii=False, indent=None if ctx.obj.get("json") else 2))


def register(root: typer.Typer) -> None:
    """Add `describe` to the CLI's root (the describe part, copier's include_describe)."""
    root.command(name="describe")(describe)
