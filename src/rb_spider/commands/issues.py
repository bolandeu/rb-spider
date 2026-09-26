from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import issues as issues_service
from ..core import storage
from . import options

CrawlIdArgument = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний.")


@output.guard
def issues(
    ctx: typer.Context,
    crawl_id: int | None = CrawlIdArgument,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сводка SEO-проблем обхода: какие проверки сработали и на скольких URL.

    Первый шаг анализа: сначала сводка, потом `spider urls --issue <code>` — сами
    URL. Сверху самое срочное: приоритет high → medium → low, внутри — по числу
    URL. Тип и приоритет — как в Screaming Frog: issue — ошибка, исправить;
    warning — проверить; opportunity — можно улучшить. Проверки считаются после
    обхода; после обновления spider пересчитать — `spider analyze`.

    Примеры:
      spider issues
      spider issues 12
      spider --json issues

    JSON: `{crawl_id, issues: [{code, group, name, type, priority, description, urls}]}`.
    Нет такого обхода или обходов нет вообще — код выхода 2.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        found = issues_service.summary(engine, crawl_id)
    data = {"crawl_id": crawl_id, "issues": [vars(s) for s in found]}
    output.emit_success(ctx, data, render_human=output.human.issues_table)


@output.guard
def urls(
    ctx: typer.Context,
    crawl_id: int | None = CrawlIdArgument,
    issue: str = typer.Option(..., "--issue", help="Код проверки из `spider issues`, например internal_client_error."),
    limit: int = typer.Option(100, "--limit", min=1, help="Сколько URL показать (всего — в поле total)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """URL, на которых сработала проверка, с кодом ответа и подробностью.

    Второй шаг после `spider issues`. `detail` зависит от проверки: цель
    редиректа, цепочка прыжков, текст ошибки соединения.

    Примеры:
      spider urls --issue internal_client_error
      spider urls 12 --issue internal_redirect_chain --limit 20
      spider --json urls --issue internal_no_response

    JSON: `{crawl_id, issue, total, urls: [{url, status_code, detail}]}`; `status_code`
    0 — ответа не было (сбой или запрет robots.txt). Неизвестный код — выход 2.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        total, rows = issues_service.urls_with(engine, crawl_id, issue, limit=limit)
    data = {"crawl_id": crawl_id, "issue": issue, "total": total, "urls": rows}
    output.emit_success(ctx, data, render_human=output.human.issue_urls_table)


@output.guard
def analyze(
    ctx: typer.Context,
    crawl_id: int | None = CrawlIdArgument,
    profile: str | None = options.ProfileOption,
    config_file: Path | None = options.ConfigFileOption,
    assignments: list[str] | None = options.SetOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Пересчитать проверки обхода без повторного скачивания сайта.

    Нужен после обновления spider (новые проверки) или смены порогов: данные
    страниц уже в базе, пересчёт занимает секунды. Пороги (раздел `thresholds`)
    берутся из текущих настроек — со всеми слоями, как у `spider crawl`, — а не
    из снимка обхода. Прежние результаты проверок этого обхода заменяются.

    Примеры:
      spider analyze
      spider analyze 12 --set thresholds.redirect_chain_hops=3

    JSON: `{crawl_id, findings}` — сколько пар «проверка — URL» найдено.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        thresholds = options.resolve(ctx, profile, config_file, assignments).settings.thresholds
        findings = issues_service.analyze(engine, crawl_id, thresholds)
    output.emit_success(
        ctx,
        {"crawl_id": crawl_id, "findings": findings},
        render_human=lambda d: output.human.echo(f"Обход #{d['crawl_id']}: найдено {d['findings']} (проверка, URL)."),
    )
