from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import typer

from .. import output
from ..core import duplicates as duplicates_service
from ..core import storage
from ..core.errors import InvalidArguments
from . import options


class Kind(StrEnum):
    all = "all"
    exact = "exact"
    near = "near"


@output.guard
def duplicates(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    kind: Kind = typer.Option(Kind.all, "--kind", help="all — все пары; exact — точные дубли; near — почти-дубли."),
    url: str | None = typer.Option(None, "--url", help="Только пары с этой страницей."),
    diff: bool = typer.Option(
        False, "--diff", help="С --url: разница текста страницы с каждой парой (нужен обход с --store-html)."
    ),
    limit: int = typer.Option(100, "--limit", min=1, help="Сколько пар показать (всего — в поле total)."),
    profile: str | None = options.ProfileOption,
    config_file: Path | None = options.ConfigFileOption,
    assignments: list[str] | None = options.SetOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Пары дублей страниц: точные (одинаковый HTML) и почти-дубли (сходство текста MinHash).

    Duplicate Details из Screaming Frog: для проверок `content_exact_duplicates` и
    `content_near_duplicates` из `spider issues`. Точный дубль показан парой со первой
    страницей своей группы, почти-дубль — каждой парой один раз. Почти-дубли есть только
    у обходов с `collect.near_duplicates = true` (extra `rb-spider[near]`); порог сходства
    и «только индексируемые» — `thresholds.near_duplicate_similarity` и
    `thresholds.duplicates_indexable_only`, меняются через `spider analyze`.

    Примеры:
      spider duplicates
      spider duplicates --kind near --limit 1000
      spider duplicates --url https://site.ru/a --diff

    JSON: `{crawl_id, kind, total, pairs: [{url, other, similarity, kind, diff?}]}`;
    `similarity` — 0–1 (у точных 1); `diff` — строки unified diff текста (по предложениям),
    null — HTML не сохранялся. `--diff` без `--url` — выход 2.
    """
    if diff and not url:
        raise InvalidArguments("--diff compares one page with its duplicates: give it --url.")
    thresholds = options.resolve(ctx, profile, config_file, assignments).settings.thresholds
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        total, pairs = duplicates_service.report(engine, crawl_id, thresholds, kind=kind.value, url=url, limit=limit)
    if diff:
        for pair in pairs:
            pair["diff"] = duplicates_service.text_diff(crawl_id, pair["url"], pair["other"])
    output.emit_success(ctx, {"crawl_id": crawl_id, "kind": kind.value, "total": total, "pairs": pairs},
                        render_human=output.human.duplicates_list)  # fmt: skip
