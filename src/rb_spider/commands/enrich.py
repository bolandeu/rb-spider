from __future__ import annotations

import dataclasses

import typer

from .. import output
from ..core import enrich as enrich_service
from ..core import storage


@output.guard
def enrichers(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать установленные обогатители — плагины, которые добавляют метрики к URL.

    Обогатитель — отдельный пакет (данные Search Console, Вебмастера, PageSpeed…)
    с entry point в группе `rb_spider.enrichers`; установить его рядом со spider:
    `uv tool install rb-spider --with <пакет>`. Плагин, который не загружается,
    показан с причиной. Запустить — `spider enrich`.

    Примеры:
      spider enrichers
      spider --json enrichers

    JSON: `{enrichers: [{name, target, description, error}]}`; `error` — null у
    рабочих плагинов.
    """
    plugins = [{k: v for k, v in dataclasses.asdict(p).items() if k != "enricher"} for p in enrich_service.discover()]
    output.emit_success(ctx, {"enrichers": plugins}, render_human=output.human.enrichers_table)


@output.guard
def enrich(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    plugins: list[str] | None = typer.Option(
        None, "--plugin", help="Запустить только этот обогатитель (можно несколько раз); по умолчанию — все."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Добавить к URL обхода метрики от обогатителей (плагинов).

    Каждый плагин получает обход (URL сайта) и пишет метрики в таблицу
    `url_metrics`; повторный запуск заменяет его прошлые метрики этого обхода.
    Метрики видны в `spider url <url>` и доступны в `spider query`
    (`SELECT * FROM url_metrics WHERE crawl_id = …`). Список плагинов — `spider enrichers`.

    Примеры:
      spider enrich
      spider enrich 12 --plugin gsc
      spider --json enrich

    JSON: `{crawl_id, stored: {плагин: число метрик}}`. Неизвестный плагин — выход 2;
    плагин упал или не загружается — выход 5 (`PROVIDER_ERROR`, в `provider` — его имя),
    его прежние метрики остаются.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        stored = enrich_service.run(engine, crawl_id, plugins or None)
    output.emit_success(ctx, {"crawl_id": crawl_id, "stored": stored}, render_human=output.human.enriched)
