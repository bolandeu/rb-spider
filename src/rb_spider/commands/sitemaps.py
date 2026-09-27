from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

import typer

from .. import output
from ..core import sitemaps as sitemaps_service
from ..core import storage

app = output.group("XML sitemap: что прочитал обход (файлы, URL, сироты) и генерация sitemap по обходу.")
Only = StrEnum("Only", {name: name for name in sitemaps_service.ONLY})


@app.command("show")
@output.guard
def show(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    only: Only = typer.Option(
        "files",
        "--only",
        help="files — файлы sitemap (размер, число URL, ошибка); urls — все URL из них; orphans — URL без "
        "ссылок на сайте (Orphan Pages); not_in_sitemap — индексируемые страницы, которых нет в sitemap.",
    ),
    limit: int = typer.Option(100, "--limit", min=1, help="Сколько строк показать (всего — в поле total)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Показать, что обход прочитал из XML sitemap, и сравнение с найденным по ссылкам.

    Sitemap читается в начале обхода с `sitemaps.crawl = true` (extra
    `rb-spider[sitemaps]`): найденные через robots.txt и стандартные пути
    (`sitemaps.discover`) и заданные `sitemaps.urls`; их URL обходятся
    (`sitemaps.follow`). Проблемы — `spider issues`, группа Sitemaps; число URL
    в sitemap и вне — `spider overview`.

    Example: spider sitemaps show
    Example: spider sitemaps show --only orphans
    Example: spider --json sitemaps show 12 --only not_in_sitemap --limit 1000

    JSON: `{crawl_id, only, total, rows}`; files — `{url, kind, bytes, urls, sitemaps, error}`
    (kind null — файл не получен, см. error), urls — `{url, source, lastmod, status_code,
    indexability_status}`, orphans — `{url, source, status_code, indexability_status}`,
    not_in_sitemap — `{url, depth, inlinks}`.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        total, rows = sitemaps_service.report(engine, crawl_id, only.value, limit)
    output.emit_success(ctx, {"crawl_id": crawl_id, "only": only.value, "total": total, "rows": rows},
                        render_human=output.human.sitemaps_rows)  # fmt: skip


@app.command("build")
@output.guard
def build(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    out_dir: Path = typer.Option(..., "--out", "-o", help="Каталог, куда записать sitemap.xml (и sitemap-N.xml)."),
    base_url: str | None = typer.Option(
        None, "--base-url", help="Где файлы будут лежать на сайте (для индекса); по умолчанию — корень стартового URL."
    ),
    include: list[str] | None = typer.Option(
        None,
        "--include",
        help="Добавить и такие страницы: noindex, canonicalised, paginated (2+), pdf. Можно несколько раз.",
    ),
    lastmod: bool = typer.Option(False, "--lastmod", help="Проставить lastmod из заголовка Last-Modified ответа."),
    images: bool = typer.Option(False, "--images", help="Image Sitemap: страницы с картинками (картинки с кодом 200)."),
    changefreq: str | None = typer.Option(
        None, "--changefreq", help="changefreq всех URL: always, hourly, daily, weekly, monthly, yearly, never."
    ),
    priority: str | None = typer.Option(
        None,
        "--priority",
        help="priority: число 0.0–1.0 для всех URL или depth — 1.0 у стартовой, на 0.1 меньше за клик.",
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сгенерировать XML sitemap (или Image Sitemap) по обходу — через rb-sitemap-xml.

    В sitemap идут индексируемые HTML-страницы сайта с кодом 200 (без страниц
    пагинации 2+); `--include` добавляет noindex, canonicalised, пагинацию, PDF. Больше
    49 999 URL — файлы sitemap-N.xml и индекс sitemap.xml. Нужен extra
    `rb-spider[sitemaps]`. Пишет только в каталог `--out`.

    Example: spider sitemaps build -o public/
    Example: spider sitemaps build 12 -o out/ --lastmod --include pdf
    Example: spider sitemaps build -o out/ --images
    Example: spider sitemaps build -o out/ --priority depth --changefreq weekly

    JSON: `{crawl_id, files: [путь…], urls}`; индекс — первым. Неизвестное значение
    `--include` / `--changefreq`, неверный `--priority` — выход 2; нет extra —
    SITEMAPS_UNAVAILABLE, выход 1.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        row, _ = storage.get_crawl(engine, crawl_id)
        base = base_url or "{0.scheme}://{0.netloc}".format(urlsplit(row.start_url))
        files, count = sitemaps_service.build(engine, crawl_id, out_dir, base_url=base, include=set(include or []),
                                              lastmod=lastmod, images=images, changefreq=changefreq,
                                              priority=priority)  # fmt: skip
    output.emit_success(ctx, {"crawl_id": crawl_id, "files": [str(f) for f in files], "urls": count},
                        render_human=output.human.sitemaps_built)  # fmt: skip
