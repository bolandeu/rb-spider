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
    max_depth: int | None = typer.Option(
        None, "--max-depth", min=0, help="Не глубже стольких кликов от старта (ключ crawl.max_depth)."
    ),
    user_agent: str | None = typer.Option(
        None,
        "--user-agent",
        help="User-Agent: пресет (googlebot, googlebot-smartphone, bingbot, yandexbot, chrome) или строка (crawl.user_agent).",
    ),
    ignore_robots: bool = typer.Option(
        False, "--ignore-robots", help="Не читать robots.txt, обходить всё (ключ crawl.robots = ignore)."
    ),
    store_html: bool | None = typer.Option(
        None, "--store-html", help="Сохранить HTML страниц сжатым рядом с базой (ключ crawl.store_html)."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Обойти сайт по ссылкам и сохранить каждую страницу в базу обходов.

    Обход в ширину от стартового URL, только внутри его хоста. Редиректы не
    проходятся автоматически: каждый шаг цепочки сохраняется как отдельная
    страница, цель редиректа обходится следом. Коды 3xx/4xx/5xx — это данные,
    а не ошибки. robots.txt читается от имени нашего User-Agent: запрещённые URL
    не скачиваются, но попадают в отчёт, Crawl-delay соблюдается (режимы —
    ключ crawl.robots). Что обходить (include/exclude, поддомены, папка, лимиты),
    скорость, заголовки и прокси — ключи раздела crawl, см. `spider config show`.
    После обхода сразу считаются проверки с порогами из
    раздела `thresholds` — смотреть в `spider issues`.

    Настройки — слоями: встроенные → глобальный конфиг → проект → `--profile` →
    `--config` → переменные `SPIDER_<РАЗДЕЛ>__<КЛЮЧ>` → флаги → `--set`. Итог
    сохраняется вместе с обходом (`spider crawls show`), проверить заранее —
    `spider config show` с теми же флагами. Проект — из `.spider/config.toml`,
    если команда запущена в проекте, иначе хост сайта.

    Примеры:
      spider crawl https://example.com/
      spider crawl https://example.com/ --profile googlebot --max-urls 1000
      spider crawl https://example.com/ --user-agent googlebot --max-depth 3
      spider crawl https://example.com/ --set 'crawl.exclude=["\\?sort="]' --set crawl.max_rps=5
      spider crawl https://example.com/ --store-html   # HTML — в spider-html.sqlite рядом с базой
      spider --json crawl https://example.com/

    Человеку — прогресс в stderr каждые 5 с и итог. JSON:
    `{crawl_id, project, start_url, status, pages, elapsed_s}`; `status` —
    finished | failed | interrupted. Неверный URL или настройка — код выхода 2.
    """
    resolved = options.resolve(
        ctx,
        profile,
        config_file,
        assignments,
        {
            "crawl.max_urls": max_urls,
            "crawl.concurrency": concurrency,
            "crawl.max_depth": max_depth,
            "crawl.user_agent": user_agent,
            "crawl.robots": "ignore" if ignore_robots else None,
            "crawl.store_html": store_html,
        },
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
            resolved.settings,
            on_progress=progress,
        )
    output.emit_success(
        ctx,
        vars(result),
        render_human=lambda d: output.human.key_values(
            f"Обход #{d['crawl_id']}: {d['status']}",
            {"проект": d["project"], "старт": d["start_url"], "страниц": d["pages"], "время, с": d["elapsed_s"]},
        ),
    )
