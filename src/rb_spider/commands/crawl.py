from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import crawl as crawl_service
from ..core import services, storage


@output.guard
def crawl(
    ctx: typer.Context,
    url: str = typer.Argument(..., help="Стартовый URL, например https://example.com/. Обходится только его хост."),
    max_urls: int | None = typer.Option(
        None, "--max-urls", min=1, help="Остановиться после стольких URL (по умолчанию — весь сайт)."
    ),
    concurrency: int = typer.Option(20, "--concurrency", min=1, help="Сколько запросов к сайту одновременно."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Обойти сайт по ссылкам и сохранить каждую страницу в базу обходов.

    Обход в ширину от стартового URL, только внутри его хоста. Редиректы не
    проходятся автоматически: каждый шаг цепочки сохраняется как отдельная
    страница, цель редиректа обходится следом. Коды 3xx/4xx/5xx — это данные,
    а не ошибки. Проект — из `.spider/config.toml`, если команда запущена в
    проекте, иначе хост сайта. База — `spider doctor` покажет путь
    (`SPIDER_DB_PATH` переопределяет).

    Примеры:
      spider crawl https://example.com/
      spider crawl https://example.com/ --max-urls 1000 --concurrency 10
      spider --json crawl https://example.com/

    Человеку — прогресс в stderr каждые 5 с и итог. JSON:
    `{crawl_id, project, start_url, status, pages, elapsed_s}`; `status` —
    finished | failed | interrupted. Неверный URL — код выхода 2.
    """
    root = services.find_project_root(Path(ctx.obj.get("project") or Path.cwd()))
    project = services.load_config(root).name if root else crawl_service.project_for(url)

    def progress(pages: int) -> None:
        if not (ctx.obj.get("json") or json_output or ctx.obj.get("quiet") or quiet):
            output.human.err_console.print(f"… {pages} URL")

    with storage.database() as engine:
        result = crawl_service.crawl_site(
            engine, url, project, max_urls=max_urls, concurrency=concurrency, on_progress=progress
        )
    output.emit_success(
        ctx,
        vars(result),
        render_human=lambda d: output.human.key_values(
            f"Обход #{d['crawl_id']}: {d['status']}",
            {"проект": d["project"], "старт": d["start_url"], "страниц": d["pages"], "время, с": d["elapsed_s"]},
        ),
    )
