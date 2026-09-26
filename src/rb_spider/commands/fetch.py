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
        None, "--list", help="Файл с URL (по одному в строке, # — комментарий) или - для stdin."
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
    profile: str | None = options.ProfileOption,
    config_file: Path | None = options.ConfigFileOption,
    assignments: list[str] | None = options.SetOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Скачать страницы и вернуть их данные — без обхода и без записи в базу.

    Общий сборщик для других инструментов и агентов: отдаёте URL — получаете
    финальный URL, код ответа, шаги редиректов, время и SEO-данные (title,
    description, h1, canonical, robots, число слов), по запросу — заголовки,
    ссылки, ресурсы, текст, Markdown и HTML. Тот же движок, что у обхода:
    браузерный отпечаток, User-Agent, прокси с паролем из хранилища ключей
    (`--set crawl.proxy_urls=…`, `--profile`), `--render` — через браузер (нужен
    `rb-spider[render]`). robots.txt не читается: URL названы вами, как у curl.
    Обойти сайт целиком — `spider crawl`. Из Python — `rb_spider.fetch`.

    Примеры:
      spider fetch https://example.com/old-page
      spider --json fetch https://a.ru/ https://b.ru/ --include links,text
      spider fetch https://spa.example/ --render --markdown          # страница для LLM
      cat urls.txt | spider --json fetch --list - --concurrency 20 --profile googlebot

    Выход: человеку — строка на URL (код, финальный URL, title, время). `--json` —
    JSON Lines, объект на URL в порядке ввода: `{url, final_url, status, redirects:
    [{url, status, location}], content_type, bytes, elapsed_ms, rendered, seo,
    refresh_url, headers?, links?, resources?, text?, markdown?, html?, error}`;
    `status` null и `error` — URL не ответил (это данные, код выхода 0).
    `--markdown` — Markdown-документы, разделённые строкой `===`. Нет URL,
    неверный `--include` — выход 2; `--render` без Playwright — выход 1.
    """
    if bool(urls) == (url_list is not None):
        raise InvalidArguments("Give URLs or --list <file>, not both (and not neither).")
    targets = read_url_list(options.read_url_source(url_list) if url_list is not None else "\n".join(urls or []))
    wanted = fetch_service.parse_include(include) | ({"markdown"} if markdown else set())
    settings = options.resolve(ctx, profile, config_file, assignments).settings.crawl
    as_json = bool(ctx.obj.get("json") or json_output)
    quiet = bool(ctx.obj.get("quiet") or quiet)

    async def run() -> None:
        stream = fetch_service.fetch_stream(targets, settings, render=render, include=wanted, concurrency=concurrency)
        first = True
        async for result in stream:
            if markdown:
                typer.echo(("" if first else "\n===\n\n") + result.to_markdown(), nl=False)
            elif as_json:
                typer.echo(json.dumps(result.to_dict(), ensure_ascii=False))
            elif not quiet:
                output.human.fetched(result.to_dict())
            first = False

    asyncio.run(run())
