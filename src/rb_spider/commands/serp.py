from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import serp as serp_service
from ..core import storage
from . import options

app = output.group("Выдача Google: ширина title и description в пикселях, сниппет по обходу и для своего текста.")


@app.command("summary")
@output.guard
def summary(
    ctx: typer.Context,
    crawl_id: int | None = typer.Argument(None, help="Номер обхода (`spider crawls list`); по умолчанию — последний."),
    limit: int = typer.Option(100, "--limit", min=1, help="Сколько страниц показать (всего — в поле total)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """SERP Summary: title и description каждой HTML-страницы — в символах и пикселях.

    Пиксели — ширина в выдаче Google (Arial: title — `thresholds.serp_title_font_px`,
    description — `serp_description_font_px`), считаются в `spider analyze`. Проблемы
    (шире / уже порогов) — `spider issues`, группы Page Titles и Meta Description;
    сниппет одной страницы — `spider url`.

    Примеры:
      spider serp summary
      spider --json serp summary 12 --limit 1000

    JSON: `{crawl_id, total, pages: [{url, title, title_chars, title_px, description,
    description_chars, description_px}]}`.
    """
    with storage.database() as engine:
        crawl_id = storage.resolve_crawl_id(engine, crawl_id)
        total, rows = serp_service.summary(engine, crawl_id, limit)
    output.emit_success(ctx, {"crawl_id": crawl_id, "total": total, "pages": rows},
                        render_human=output.human.serp_summary)  # fmt: skip


@app.command("preview")
@output.guard
def preview(
    ctx: typer.Context,
    title: str = typer.Option("", "--title", help="Title, который проверить."),
    description: str = typer.Option("", "--description", help="Meta description, который проверить."),
    url: str = typer.Option("https://example.com/", "--url", help="URL страницы — строка адреса сниппета."),
    profile: str | None = options.ProfileOption,
    config_file: Path | None = options.ConfigFileOption,
    assignments: list[str] | None = options.SetOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Предпросмотр сниппета Google для своего title и description — без обхода.

    Для подбора текста до публикации: ширина в пикселях и как выдача обрежет
    title и description (по словам, с «…»). Пороги и кегли — `thresholds.title_max_px`,
    `description_max_px`, `serp_*_font_px` (из `--profile` / `--set`).

    Примеры:
      spider serp preview --title "Купить диван в Москве — каталог" --description "Доставка за день…"
      spider --json serp preview --title "…" --set thresholds.title_max_px=600

    JSON: `{url, title, title_px, title_truncated, description, description_px,
    description_truncated}`; title / description — как их покажет выдача.
    """
    thresholds = options.resolve(ctx, profile, config_file, assignments).settings.thresholds
    output.emit_success(ctx, serp_service.snippet(url, title, description, thresholds),
                        render_human=output.human.serp_preview)  # fmt: skip
