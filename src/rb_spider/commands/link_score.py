from __future__ import annotations

import typer

from .. import output
from ..core import link_score as link_score_service
from ..core import storage


@output.guard
def link_score(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    limit: int = typer.Option(20, "--limit", min=1, help="Сколько страниц с наибольшим Link Score показать."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Link Score: посчитать внутренний PageRank страниц обхода (0–100) по перелинковке сайта.

    Какие страницы сайт «продвигает» ссылками сильнее всего, а какие получают мало
    веса. Считается только по запросу: PageRank по follow-ссылкам сайта (каждая пара
    «откуда → куда» один раз), шкала логарифмическая, как у Screaming Frog, — самая
    сильная страница 100, самая слабая 1. Результат сохраняется в колонку
    `link_score` страниц (`spider url`, `spider export`, `spider query`); повторный
    запуск пересчитывает. Нужны внутренние ссылки обхода
    (`collect.internal_links.store`, по умолчанию включено).

    Примеры:
      spider link-score
      spider link-score 12 --limit 100
      spider --json link-score

    JSON: `{crawl_id, pages, top: [{url, link_score, inlinks}]}`; pages — сколько
    страниц получили оценку. Обход без сохранённых внутренних ссылок — выход 2,
    `INTERNAL_LINKS_NOT_COLLECTED` (переобойти с `--set collect.internal_links.store=true`).
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        data = link_score_service.compute_and_store(engine, crawl_id, limit)
    output.emit_success(ctx, {"crawl_id": crawl_id, **data}, render_human=output.human.link_score)
