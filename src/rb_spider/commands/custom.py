from __future__ import annotations

import typer

from .. import output
from ..core import custom_report, storage
from ..core.errors import InvalidArguments


@output.guard
def custom(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    search: str | None = typer.Option(
        None, "--search", help="Страницы, где нашёлся этот поиск (имя из custom.search)."
    ),
    extract: str | None = typer.Option(None, "--extract", help="Значения этого извлечения (имя из custom.extract)."),
    without: bool = typer.Option(False, "--without", help="С --search: HTML-страницы, где он ничего не нашёл."),
    limit: int = typer.Option(100, "--limit", min=1, help="Сколько строк показать (всего — в поле total)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Результаты своих поисков и извлечений (Custom Search / Custom Extraction).

    Правила задаются в разделе `[custom]` конфига до обхода: `[[custom.search]]` —
    сколько раз текст или регулярное выражение встречается в HTML, тексте или
    элементе; `[[custom.extract]]` — значения по CSS, XPath (extra `rb-spider[xpath]`)
    или регулярному выражению. Без опций — список правил обхода с числом страниц;
    `--search` / `--extract` — страницы одного правила.

    Примеры:
      spider custom
      spider custom --search GTM --without          # где счётчика нет
      spider --json custom 12 --extract price --limit 1000

    JSON: без опций — `{crawl_id, rules: [{kind, name, pages, without}]}` (without —
    HTML-страниц без совпадений, у извлечений null); с опцией — `{crawl_id, kind, name,
    total, rows: [{url, value, n}]}`: у поиска n — число совпадений, у извлечения —
    номер значения на странице. `--search` и `--extract` вместе, `--without` без
    `--search` — выход 2.
    """
    if search and extract:
        raise InvalidArguments("Choose one: --search or --extract.")
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        if not (search or extract):
            if without:
                raise InvalidArguments("--without lists pages a search found nothing on: use it with --search.")
            data: dict = {"crawl_id": crawl_id, "rules": custom_report.rules(engine, crawl_id)}
        else:
            kind, name = ("search", search) if search else ("extract", extract or "")
            total, rows = custom_report.rows(engine, crawl_id, kind, name, without=without, limit=limit)
            data = {"crawl_id": crawl_id, "kind": kind, "name": name, "total": total, "rows": rows}
    output.emit_success(ctx, data, render_human=output.human.custom_view)
