from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import typer

from .. import output
from ..core import crawl as crawl_service
from ..core import services, storage
from ..core.errors import InvalidArguments
from . import options


@output.guard
def crawl(
    ctx: typer.Context,
    url: str | None = typer.Argument(
        None, help="Стартовый URL, например https://example.com/. Обходится только его хост. Не нужен с --list."
    ),
    url_list: str | None = typer.Option(
        None,
        "--list",
        help="Режим списка: файл с URL (по одному в строке, # — комментарий; CSV или Excel с колонкой url / "
        "address / loc; XML sitemap) или - для stdin; обходятся только они и их редиректы (ключ crawl.mode = list).",
    ),
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
    detach: bool = typer.Option(
        False, "--detach", help="Запустить обход в фоне и сразу вернуться; следить — `spider status`."
    ),
    render: Render | None = typer.Option(
        None,
        "--render",
        help="JS-рендеринг HTML-страниц браузером: never, always или auto (ключ crawl.render, по умолчанию never).",
    ),
    store_html: bool | None = typer.Option(
        None, "--store-html", help="Сохранить HTML страниц сжатым рядом с базой (ключ crawl.store_html)."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Обойти сайт по ссылкам (или список URL) и сохранить каждую страницу в базу обходов.

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

    Example: spider crawl https://example.com/
    Example: spider crawl https://example.com/ --profile googlebot --max-urls 1000
    Example: spider crawl https://example.com/ --user-agent googlebot --max-depth 3
    Example: spider crawl https://example.com/ --set 'crawl.exclude=["\\?sort="]' --set crawl.max_rps=5
    Example: spider crawl https://example.com/ --store-html   # HTML — в spider-html.sqlite рядом с базой
    Example: spider --json crawl https://example.com/
    Example: spider crawl https://spa.example/ --render always --set crawl.render_wait_ms=1000
    Example: spider crawl --list old-urls.txt              # аудит списка, например после миграции
    Example: cat urls.txt | spider crawl --list - --detach
    Example: spider crawl https://example.com/ --set sitemaps.crawl=true   # и сравнить с sitemap

    Режим списка (`--list`, как List mode в Screaming Frog) — аудит заданных URL
    без перехода по ссылкам, например перед миграцией или после неё: каждый URL
    скачивается (глубина 0), редиректы (3xx, meta и HTTP Refresh) проходятся до
    конца, на какой бы хост они ни вели. «Свой сайт» для проверок — хосты из
    списка. Список — URL построчно, CSV или Excel (.xlsx) с колонкой url / address / loc
    (выгрузка Screaming Frog или `spider export`) или XML sitemap (`<urlset>`). Результат —
    обычный обход: issues, urls, redirects, links работают.

    XML sitemap сайта (`sitemaps.crawl`, extra `rb-spider[sitemaps]`) читается в
    начале обхода: его URL тоже обходятся, а проверки группы Sitemaps сравнивают
    его с найденным по ссылкам — `spider sitemaps show`.

    JS-сайт (контент, ссылки или title появляются только после скриптов) —
    `--render always`: HTML-страницы с кодом 200 после обычного запроса ещё и
    открываются в браузере, SEO-данные берутся из готового DOM, а коды ответа,
    редиректы и ресурсы проверяются как обычно. Нужен `rb-spider[render]`; браузер
    находится сам — сборка Playwright, любой Chromium из кэша Playwright или Google
    Chrome (свой путь — crawl.render_browser). Вкладок — crawl.render_tabs, ожидание
    скриптов — crawl.render_wait_ms, окно — crawl.render_viewport. Медленнее обычного
    обхода в разы. `--render auto` — рендерит первые crawl.render_auto_sample страниц
    и продолжает, только если JS на них что-то поменял. С рендерингом работают
    проверки группы JavaScript (исходный HTML против отрендеренного, JS-редиректы,
    ошибки консоли — `spider report javascript`).

    Прерванный обход (Ctrl-C, падение, kill -9) продолжается без потерь:
    `spider crawls resume`. Долгий обход — в фоне: `--detach`, прогресс — `spider status`.

    Прокси (`crawl.proxy_urls`, удобно — в профиле) несёт весь трафик к сайту:
    страницы, robots.txt, sitemap, браузер. Перед стартом он проверяется запросом
    к robots.txt. Не работает (не оплачен, неверный пароль, модем выключен) — по
    ключу `crawl.proxy_fallback`: `stop` (по умолчанию) — обход остановлен, код 5
    `PROXY_UNAVAILABLE`, продолжить — `spider crawls resume`; в терминале spider
    сначала спросит, идти ли без прокси. `direct` — идти без прокси. То же посреди
    обхода после `crawl.proxy_max_failures` ошибок прокси подряд: упавшие из-за
    него URL не записываются, а запрашиваются снова.
    Example: spider crawl https://example.com/ --profile mobile-proxy   # свой профиль с crawl.proxy_urls

    Человеку — прогресс в stderr каждые 5 с и итог. JSON:
    `{crawl_id, project, start_url, status, pages, elapsed_s, proxy_down}`; `status` —
    finished | failed | interrupted; `proxy_down` — почему обход шёл без прокси
    (`direct`), иначе null. С `--detach` — сразу `{crawl_id, project,
    detached, pid, log}`. Неверный URL, пустой или битый список, настройка — код
    выхода 2; `--render always|auto` без Playwright — код 1, `RENDER_UNAVAILABLE`;
    прокси не работает — код 5, `PROXY_UNAVAILABLE`.
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
            "crawl.render": render.value if render else None,
        },
    )
    if (url is None) == (url_list is None):
        raise InvalidArguments("Give either a start URL or --list <file>, not both.")
    urls = crawl_service.read_url_list(options.read_url_source(url_list)) if url_list is not None else None
    start_url = urls[0] if urls else url
    root = services.find_project_root(Path(ctx.obj.get("project") or Path.cwd()))
    project = services.load_config(root).name if root else crawl_service.project_for(start_url or "")

    def progress(pages: int) -> None:
        if not (ctx.obj.get("json") or json_output or ctx.obj.get("quiet") or quiet):
            output.human.err_console.print(f"… {pages} URL")

    with storage.database() as engine:
        if urls:
            crawl_id = crawl_service.register_list_crawl(engine, urls, project, resolved.settings)
        else:
            crawl_id = crawl_service.register_crawl(engine, url or "", project, resolved.settings)
        if detach:
            pid, log = crawl_service.detach(crawl_id)
            data = {"crawl_id": crawl_id, "project": project, "detached": True, "pid": pid, "log": str(log)}
            output.emit_success(ctx, data, render_human=output.human.detached)
            return
        ask = options.proxy_question(ctx, json_output)
        result = crawl_service.run_crawl(engine, crawl_id, on_progress=progress, ask=ask)
    output.emit_success(ctx, vars(result), render_human=output.human.crawl_result)


class Render(StrEnum):
    never = "never"
    always = "always"
    auto = "auto"
