"""Files this tool keeps in its user data dir, declared for `describe --json` (x-rb-data).

The dir is `platformdirs.user_data_path(TOOL)` (`core/db.py` keeps the local SQLite
file there; `describe` lists that one itself). Add an entry for every other file or
family of files the tool writes there, so the platform knows what it holds.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataFile:
    path: str  # relative to the user data dir; a glob for a family of files ("exports/*.csv")
    kind: str  # "data": lost when deleted | "cache": fetched or rebuilt again on demand
    description: str


DATA_FILES: tuple[DataFile, ...] = (
    # core/storage.py: beside the database, one per remote database when SPIDER_DATABASE_URL is set
    DataFile("spider-html*.sqlite", "data", "Stored HTML of crawled pages (crawl.store_html), zstd, SQLite"),
    DataFile(
        "spider-screenshots*/*/*.jpg", "data", "Screenshots of rendered pages (crawl.render_screenshots), per crawl"
    ),
)
