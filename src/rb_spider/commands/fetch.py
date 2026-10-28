"""`spider fetch`: pages without a crawl, through the page storage (core/fetch.py, core/fetch_store.py)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from .. import output
from ..core import fetch as fetch_service
from ..core.crawl import read_url_list
from ..core.errors import InvalidArguments
from . import options


@output.guard
def fetch(
    ctx: typer.Context,
    urls: list[str] | None = typer.Argument(None, help="URL страниц, например https://example.com/page."),
    url_list: str | None = typer.Option(
        None,
        "--list",
        help="Файл с URL (по одному в строке, # — комментарий; CSV с колонкой url; XML sitemap) или - для stdin.",
    ),
    render: bool = typer.Option(False, "--render", help="Открыть HTML-страницы в браузере (JS), как crawl.render."),
    include: str = typer.Option(
        "",
        "--include",
        help=f"Что добавить к SEO-данным, через запятую: {', '.join(fetch_service.INCLUDE)}.",
    ),
    markdown: bool = typer.Option(
        False, "--markdown", help="Вывести каждую страницу Markdown-документом для LLM (основной контент)."
    ),
    concurrency: int | None = typer.Option(
        None, "--concurrency", min=1, help="Сколько страниц скачивать одновременно (ключ crawl.concurrency)."
    ),
    fresh: bool = typer.Option(
        False, "--fresh", help="Не брать страницы из хранилища: скачать каждый URL заново и сохранить новую версию."
    ),
    max_age: float | None = typer.Option(
        None,
        "--max-age",
        min=0,
        help="Сохранённая страница старше стольких дней скачивается заново (по умолчанию — срок SPIDER_CACHE_TTL_DAYS, 90).",
    ),
    profile: str | None = options.ProfileOption,
    config_file: Path | None = options.ConfigFileOption,
    assignments: list[str] | None = options.SetOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Скачать страницы и вернуть их данные — без обхода, повтор в пределах срока — из хранилища страниц.

    Общий сборщик для других инструментов и агентов: отдаёте URL — получаете
    финальный URL, код ответа, шаги редиректов, время и SEO-данные (title,
    description, h1, canonical, robots, число слов), по запросу — заголовки,
    ссылки, ресурсы, текст, Markdown и HTML. Тот же движок, что у обхода:
    браузерный отпечаток, User-Agent, прокси с паролем из хранилища ключей
    (`--set crawl.proxy_urls=…`, `--profile`), `--render` — через браузер (нужен
    `rb-spider[render]`, тоже через прокси). Прокси проверяется перед первым скачиваемым URL
    и снова после `crawl.proxy_max_failures` URL подряд без ответа через него; не
    работает — по `crawl.proxy_fallback`, как у `spider crawl` (перед первым URL в терминале — вопрос). robots.txt не читается: URL названы вами, как у curl.
    `--list` — URL построчно, CSV с колонкой url / address / loc или XML sitemap.
    Обойти сайт целиком — `spider crawl`. Из Python — `rb_spider.fetch`.

    Хранилище страниц: HTML-ответ с кодом ниже 500 (кроме 429) сохраняется —
    индекс в таблице spider_fetches базы spider, исходник страницы и Markdown —
    файлом zstd в каталоге SPIDER_CACHE_DIR (по умолчанию кэш пользователя,
    на Mac ~/Library/Caches/spider/fetch). Повторный запрос того же URL в том же
    режиме (`--render` или без) в пределах срока берётся из хранилища: сайт не
    запрашивается, даже прокси не проверяется. Не сохраняются: URL без ответа,
    5xx, 429, не HTML. Срок — SPIDER_CACHE_TTL_DAYS (дней, по умолчанию 90),
    предел размера файлов — SPIDER_CACHE_MAX_GB (по умолчанию без предела); раз в
    день spider сам удаляет просроченное, затем самое старое сверх предела.

    Example: spider fetch https://example.com/old-page
    Example: spider --json fetch https://a.ru/ https://b.ru/ --include links,text
    Example: spider fetch https://spa.example/ --render --markdown          # страница для LLM
    Example: cat urls.txt | spider --json fetch --list - --concurrency 20 --profile googlebot
    Example: spider fetch https://example.com/ --profile mobile-proxy   # свой профиль с crawl.proxy_urls
    Example: spider --json fetch https://example.com/price --max-age 7  # не старше недели
    Example: spider fetch https://example.com/ --fresh                 # мимо хранилища

    Выход: человеку — строка на URL (код, финальный URL, title, время; «из
    хранилища» — страница из хранилища). `--json` — JSON Lines, объект на URL в
    порядке ввода: `{url, final_url, status, redirects: [{url, status, location}],
    content_type, bytes, elapsed_ms, rendered, seo, refresh_url, headers?, links?,
    resources?, text?, markdown?, html?, error, url_key, domain_key, content_hash,
    cache_key, fetched_at, from_cache, via}`; `status` null и `error` — URL не ответил
    (это данные, код выхода 0). `url_key`, `domain_key` — общие ключи rb-keys (null —
    не веб-адрес); `content_hash` — SHA-256 сохранённого исходника, `cache_key` —
    сохранённая версия (оба null — не сохранено); `via` — как пришла страница: `proxy` (через
    прокси), `direct` (напрямую: прокси не задан или отключён по `crawl.proxy_fallback`), `cache` (из
    хранилища); `fetched_at` — когда скачано (ISO
    8601 UTC; из хранилища — когда сохранено); `from_cache` — ответ из хранилища.
    `--markdown` — Markdown-документы, разделённые строкой `===`. Нет URL,
    неверный `--include` — выход 2; `--render` без Playwright — выход 1; прокси не
    работает — выход 5, `PROXY_UNAVAILABLE`; база недоступна — выход 5.
    """
    if bool(urls) == (url_list is not None):
        raise InvalidArguments("Give URLs or --list <file>, not both (and not neither).")
    targets = read_url_list(options.read_url_source(url_list) if url_list is not None else "\n".join(urls or []))
    wanted = fetch_service.parse_include(include) | ({"markdown"} if markdown else set())
    settings = options.resolve(ctx, profile, config_file, assignments).settings.crawl
    as_json = bool(ctx.obj.get("json") or json_output)
    quiet = bool(ctx.obj.get("quiet") or quiet)

    async def run() -> None:
        ask = options.proxy_question(ctx, as_json)
        stream = fetch_service.fetch_stream(
            targets, settings, render=render, include=wanted, concurrency=concurrency, ask=ask,
            store=True, fresh=fresh, max_age=max_age,
        )  # fmt: skip
        first = True
        async for result in stream:
            if markdown:
                typer.echo(("" if first else "\n===\n\n") + result.to_markdown(), nl=False)
            elif as_json:
                typer.echo(json.dumps(result.to_dict(), ensure_ascii=False))
            elif not quiet:
                output.human.fetched(result.to_dict(), proxies_set=bool(settings.proxy_urls))
            first = False

    asyncio.run(run())
