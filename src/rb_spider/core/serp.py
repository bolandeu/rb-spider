"""SERP: how wide a title and a description are in Google's results, in pixels, and how they'd be cut.

Google draws results in Arial — titles at 20px, snippets at 14px on desktop (thresholds.serp_*_font_px).
A text's width is the sum of its characters' advances from data/arial_widths.json (scripts/build_font_widths.py);
a character outside the table (emoji, CJK…) counts as a wide one, the width of "W". Widths are computed after the
crawl, in `analyze` (pages.title_px / description_px), so changing a font size needs no new crawl.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from urllib.parse import unquote, urlsplit

import sqlalchemy as sa

from . import storage
from .settings import ThresholdSettings

ELLIPSIS = " …"
_BATCH = 5000


@cache
def _table() -> tuple[dict[str, int], int, int]:
    data = json.loads(resources.files("rb_spider.data").joinpath("arial_widths.json").read_text(encoding="utf-8"))
    widths = {chr(int(code)): advance for code, advance in data["widths"].items()}
    return widths, data["units_per_em"], widths["W"]


def width(text: str, font_px: float) -> int:
    """Pixel width of `text` in Arial at `font_px`, rounded."""
    widths, em, wide = _table()
    return round(sum(widths.get(char, wide) for char in text) * font_px / em)


def truncate(text: str, max_px: float, font_px: float) -> tuple[str, bool]:
    """`text` as Google would show it in `max_px`: cut at a word boundary with " …" when too wide."""
    if width(text, font_px) <= max_px:
        return text, False
    widths, em, wide = _table()
    budget = max_px * em / font_px - sum(widths.get(c, wide) for c in ELLIPSIS)
    used, cut = 0, 0
    for index, char in enumerate(text):
        used += widths.get(char, wide)
        if used > budget:
            break
        cut = index + 1
    shown = text[:cut]
    if " " in shown.strip():  # a whole word rather than half of one, as Google does
        shown = shown[: shown.rstrip().rfind(" ")]
    return shown.rstrip(" ,.;:—-") + ELLIPSIS, True


def compute(conn: sa.Connection, crawl_id: int, thresholds: ThresholdSettings) -> None:
    """Fill pages.title_px / description_px of the site's HTML pages, a batch at a time."""
    select = sa.text(
        "SELECT id, title, meta_description FROM spider_pages WHERE crawl_id = :crawl_id AND NOT coalesce(external, FALSE)"
        " AND parsed AND (title IS NOT NULL OR meta_description IS NOT NULL) AND id > :after ORDER BY id"
        " LIMIT :limit"
    )
    update = sa.text("UPDATE spider_pages SET title_px = :t, description_px = :d WHERE id = :id")
    after = 0
    while rows := conn.execute(select, {"crawl_id": crawl_id, "after": after, "limit": _BATCH}).all():
        conn.execute(update, [
            {"id": rowid, "t": width(title, thresholds.serp_title_font_px) if title else None,
             "d": width(description, thresholds.serp_description_font_px) if description else None}
            for rowid, title, description in rows
        ])  # fmt: skip
        after = rows[-1][0]


def display_url(url: str) -> str:
    """The URL line of a result: host › path › segments, decoded, as Google prints it."""
    parts = urlsplit(url)
    segments = [unquote(s) for s in parts.path.split("/") if s]
    return " › ".join([parts.netloc, *segments])


def snippet(url: str, title: str | None, description: str | None, thresholds: ThresholdSettings) -> dict:
    """SERP Snippet: the result as Google would draw it (desktop), with widths and whether each part is cut."""
    title_font, description_font = thresholds.serp_title_font_px, thresholds.serp_description_font_px
    shown_title, title_cut = truncate(title or "", thresholds.title_max_px, title_font)
    shown_description, description_cut = truncate(description or "", thresholds.description_max_px, description_font)
    return {
        "url": display_url(url),
        "title": shown_title,
        "title_px": width(title or "", title_font),
        "title_truncated": title_cut,
        "description": shown_description,
        "description_px": width(description or "", description_font),
        "description_truncated": description_cut,
    }


SUMMARY = (
    "SELECT url, title, length(title) AS title_chars, title_px, meta_description AS description,"
    " length(meta_description) AS description_chars, description_px FROM spider_pages WHERE crawl_id = :crawl_id"
    " AND NOT coalesce(external, FALSE) AND parsed AND status_code = 200 AND content_type LIKE '%html%'"
)


def summary(engine: sa.Engine, crawl_id: int, limit: int | None = None) -> tuple[int, list[dict]]:
    """SERP Summary: every HTML page of the site with its title and description, in characters and pixels."""
    with engine.connect() as conn:
        total = conn.execute(sa.text(f"SELECT count(*) FROM ({SUMMARY})"), {"crawl_id": crawl_id}).scalar_one()  # noqa: S608
        rows = conn.execute(
            sa.text(f"{SUMMARY} ORDER BY url LIMIT :limit"),
            {"crawl_id": crawl_id, "limit": storage.NO_LIMIT if limit is None else limit},
        ).mappings()
        return total, [dict(row) for row in rows]
