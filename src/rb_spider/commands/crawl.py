from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import crawl as crawl_service
from ..core import services, storage
from . import options


@output.guard
def crawl(
    ctx: typer.Context,
    url: str = typer.Argument(..., help="Стартовый URL, например https://example.com/. Обходится только его хост."),
    profile: str | None = options.ProfileOption,
    config_file: Path | None = options.ConfigFileOption,
    assignments: list[str] | None = options.SetOption,
    max_urls: int | None = typer.Option(
        None, "--max-urls", min=1, help="Остановиться после стольких URL (ключ crawl.max_urls; не задан — весь сайт)."
    ),
    concurrency: int | None = typer.Option(
        None, "--concurrency", min=1, help="Сколько запросов одновременно (ключ crawl.concurrency, по умолчанию 20)."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Обойти сайт по ссылкам и сохранить каждую страницу в базу обходов.

    Обход в ширину от стартового URL, только внутри его хоста. Редиректы не
    проходятся автоматически: каждый шаг цепочки сохраняется как отдельная
    страница, цель редиректа обходится следом. Коды 3xx/4xx/5xx — это данные,
    а не ошибки. robots.txt соблюдается: запрещённые URL не скачиваются, но
    попадают в отчёт. После обхода сразу считаются проверки — `spider issues`.

    Настройки — слоями: встроенные → глобальный конфиг → проект → `--profile` →
    `--config` → переменные `SPIDER_<РАЗДЕЛ>__<КЛЮЧ>` → флаги → `--set`. Итог
    сохраняется вместе с обходом (`spider crawls show`), проверить заранее —
    `spider config show` с теми же флагами. Проект — из `.spider/config.toml`,
    если команда запущена в проекте, иначе хост сайта.

    Примеры:
      spider crawl https://example.com/
      spider crawl https://example.com/ --profile googlebot --max-urls 1000
      spider crawl https://example.com/ --set crawl.respect_robots=false
      spider --json crawl https://example.com/

    Человеку — прогресс в stderr каждые 5 с и итог. JSON:
    `{crawl_id, project, start_url, status, pages, elapsed_s}`; `status` —
    finished | failed | interrupted. Неверный URL или настройка — код выхода 2.
    """
    resolved = options.resolve(
        ctx, profile, config_file, assignments, {"crawl.max_urls": max_urls, "crawl.concurrency": concurrency}
    )
    root = services.find_project_root(Path(ctx.obj.get("project") or Path.cwd()))
    project = services.load_config(root).name if root else crawl_service.project_for(url)

    def progress(pages: int) -> None:
        if not (ctx.obj.get("json") or json_output or ctx.obj.get("quiet") or quiet):
            output.human.err_console.print(f"… {pages} URL")

    with storage.database() as engine:
        result = crawl_service.crawl_site(
            engine,
            url,
            project,
            resolved.settings.crawl,
            on_progress=progress,
            snapshot=resolved.settings.model_dump(mode="json"),
        )
    output.emit_success(
        ctx,
        vars(result),
        render_human=lambda d: output.human.key_values(
            f"Обход #{d['crawl_id']}: {d['status']}",
            {"проект": d["project"], "старт": d["start_url"], "страниц": d["pages"], "время, с": d["elapsed_s"]},
        ),
    )
