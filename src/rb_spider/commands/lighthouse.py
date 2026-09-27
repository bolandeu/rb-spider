from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import typer

from .. import output
from ..core import crawl as crawl_service
from ..core import issues as issues_service
from ..core import lighthouse as lighthouse_service
from ..core import storage
from ..core.errors import InvalidArguments
from ..core.extract import normalize_url
from . import options


class Strategy(StrEnum):
    mobile = "mobile"
    desktop = "desktop"


class Source(StrEnum):
    local = "local"
    psi = "psi"


@output.guard
def lighthouse(
    ctx: typer.Context,
    urls: list[str] | None = typer.Argument(None, help="Какие страницы обхода замерить; по умолчанию — выборка."),
    crawl_id: int | None = typer.Option(None, "--crawl", help="Номер обхода; по умолчанию — последний."),
    url_list: str | None = typer.Option(
        None, "--list", help="Файл со списком URL (как у `spider crawl --list`); - — stdin."
    ),
    every: bool = typer.Option(False, "--all", help="Все HTML-страницы обхода (долго: ~10–30 с на страницу)."),
    strategy: Strategy | None = typer.Option(
        None, "--strategy", help="mobile или desktop (ключ lighthouse.strategy, по умолчанию mobile)."
    ),
    source: Source | None = typer.Option(
        None,
        "--source",
        help="local — Lighthouse на этой машине, psi — PageSpeed Insights API (ключ lighthouse.source, по умолчанию local).",
    ),
    dry_run: bool = output.DryRunOption,
    profile: str | None = options.ProfileOption,
    config_file: Path | None = options.ConfigFileOption,
    assignments: list[str] | None = options.SetOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Скорость и мобильные проверки страниц: Lighthouse на этой машине или PageSpeed Insights.

    Проблемы скорости обычно общие для шаблона — одни и те же скрипты, стили и
    картинки на всех карточках. Поэтому без URL замеряется выборка типовых посадочных:
    главная и по `lighthouse.per_template` страниц на шаблон (папка и глубина пути) с
    наибольшим числом входящих ссылок, не больше `lighthouse.max_pages`. Конкретные
    страницы — аргументами или `--list`, все — `--all`. Итог — проверки групп PageSpeed
    (19) и Mobile (`spider issues`); повторный запуск заменяет замеры этих страниц.
    `--dry-run` — только показать, какие страницы будут замерены.

    Источник (`--source`, ключ `lighthouse.source`):
    - local (по умолчанию) — Lighthouse на этой машине, без ключей API; видит и
      закрытые, и локальные сайты. Нужны Node.js и Lighthouse: `npm install -g lighthouse`
      или `--set lighthouse.command="npx --yes lighthouse"`. Chrome — `lighthouse.chrome`,
      иначе `crawl.render_browser` или Chromium из кэша Playwright.
    - psi — PageSpeed Insights API: те же аудиты с серверов Google плюс данные
      реальных пользователей Chrome (CrUX: LCP, INP, CLS, FCP, TTFB страницы и всего
      сайта — в `spider url` и `spider export lighthouse`). Только публичные страницы.
      Нужен extra `gsc` и ключ API у gsc: `gsc auth login --provider pagespeed`;
      лимиты и повторы — у gsc, одновременно — `lighthouse.psi_concurrency` страниц.
    Mobile: ширина контента и размер шрифта меряются в браузере на этой машине при
    любом источнике (нужен extra `render`).

    Примеры:
      spider lighthouse --dry-run
      spider lighthouse
      spider lighthouse https://example.com/ https://example.com/catalog/ --strategy desktop
      spider lighthouse --source psi

    JSON: `{crawl_id, strategy, source, dry_run, pages: [{url, ok, error, performance, metrics:
    {lcp_ms, fcp_ms, cls, tbt_ms, speed_index_ms}, failed: [аудиты]}], findings}`; с `--dry-run` —
    `{crawl_id, strategy, source, dry_run, urls}`. Ошибка на странице — `ok: false` и `error`,
    остальные замеряются. Lighthouse не найден — выход 1, `LIGHTHOUSE_UNAVAILABLE`; нет gsc —
    выход 1, `PAGESPEED_UNAVAILABLE`; нет или отклонён ключ PSI — выход 3, `AUTH_REQUIRED`;
    дневная квота PSI — выход 5 (замеренное до неё сохранено); URL не из обхода или `--all`
    вместе с URL — выход 2.
    """
    settings = options.resolve(ctx, profile, config_file, assignments).settings
    chosen = {k: v.value for k, v in (("strategy", strategy), ("source", source)) if v is not None}
    if chosen:
        settings = settings.model_copy(update={"lighthouse": settings.lighthouse.model_copy(update=chosen)})
    targets = [normalize_url(u) for u in urls or []]
    if url_list is not None:
        targets += crawl_service.read_url_list(options.read_url_source(url_list))
    if every and targets:
        raise InvalidArguments("--all measures every page: give no URLs with it.")
    lh = settings.lighthouse
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        pages = lighthouse_service.pages_to_measure(engine, crawl_id, targets, every, lh)
        if dry_run:
            data = {
                "crawl_id": crawl_id,
                "strategy": lh.strategy,
                "source": lh.source,
                "dry_run": True,
                "urls": list(pages),
            }
            output.emit_success(ctx, data, render_human=output.human.lighthouse_plan)
            return
        results = []
        for page in lighthouse_service.run(engine, crawl_id, pages, settings):
            results.append({"url": page.url, "ok": page.ok, "error": page.error, "performance": page.performance,
                            "metrics": page.metrics, "failed": page.failed})  # fmt: skip
            if not ctx.obj.get("json") and not ctx.obj.get("quiet"):
                output.human.lighthouse_progress(results[-1])
        findings = issues_service.refresh(engine, crawl_id, issues_service.LIGHTHOUSE_CODES, settings.thresholds)
    data = {
        "crawl_id": crawl_id,
        "strategy": lh.strategy,
        "source": lh.source,
        "dry_run": False,
        "pages": results,
        "findings": findings,
    }
    output.emit_success(ctx, data, render_human=output.human.lighthouse_done)
