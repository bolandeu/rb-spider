from __future__ import annotations

import typer

from .. import output
from ..core import source as source_service
from ..core import storage
from ..core.errors import InvalidArguments
from ..core.extract import normalize_url


@output.guard
def source(
    ctx: typer.Context,
    url: str = typer.Argument(..., help="URL из обхода."),
    crawl_id: int | None = typer.Option(None, "--crawl", help="Номер обхода; по умолчанию — последний."),
    rendered: bool = typer.Option(False, "--rendered", help="HTML после выполнения JavaScript (DOM из браузера)."),
    diff: bool = typer.Option(False, "--diff", help="Что изменил JavaScript: diff исходного HTML и отрендеренного."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """View Source: HTML страницы — как его отдал сервер, после JavaScript или разница между ними.

    Нужен HTML, сохранённый при обходе (`--store-html`); отрендеренный — только у
    страниц, открытых в браузере (`--render always|auto`). Что именно поменял JS в
    title, description, H1, canonical, ссылках — проверки группы JavaScript
    (`spider issues`); эта команда показывает сам код.

    Example: spider source https://example.com/ > page.html
    Example: spider source https://example.com/app --rendered
    Example: spider source https://example.com/app --diff

    Человеку — HTML или diff как есть (для перенаправления в файл). JSON: `{crawl_id,
    url, mode, html}` или с `--diff` — `{crawl_id, url, mode, diff: [строки], truncated}`.
    HTML не сохранён или страница не рендерилась — выход 2. `--rendered` и `--diff`
    вместе — выход 2.
    """
    if rendered and diff:
        raise InvalidArguments("Choose one: --rendered or --diff.")
    mode = "diff" if diff else "rendered" if rendered else "raw"
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
    data = source_service.view(crawl_id, normalize_url(url), mode)
    output.emit_success(ctx, {"crawl_id": crawl_id, "url": normalize_url(url), "mode": mode, **data},
                        render_human=output.human.page_source)  # fmt: skip
