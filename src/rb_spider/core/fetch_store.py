"""The page storage of `spider fetch` (ADR 0001): a repeat fetch of a URL within its term comes from here, not the site.

- Index: table `spider_fetches` (kind cache, schema `cache` on PostgreSQL), one row per (url_key, fetch mode); a
  new fetch replaces the row and deletes the old file.
- Bodies: one zstd file per stored fetch in `SPIDER_CACHE_DIR` (default: the user cache dir, `…/spider/fetch`),
  named by its random `cache_key`, under a folder of the key's first two characters. The file is one JSON line —
  the response data (`RESPONSE_FIELDS`, `headers`) and the Markdown of the main content — then the page source that
  was parsed (raw HTML, or the rendered DOM).
- Term and limit come from the environment: `SPIDER_CACHE_TTL_DAYS` (default 90), `SPIDER_CACHE_MAX_GB` (GB = 10**9
  bytes; default no limit). The cleanup runs when a run opens the storage, at most once a day (`CLEANUP_MARKER` holds
  the time of the last one): expired rows and files go, then the oldest until the files fit the limit, then the
  files without a row older than `ORPHAN_AGE` (a run stopped between the file and its row; a younger one may be a
  save in progress).

What is stored is the fetcher's decision (core/fetch.py); this module keeps it and gives it back.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import platformdirs
import sqlalchemy as sa
import zstandard

from .._distribution import TOOL
from . import storage
from .errors import InvalidArguments
from .tables import fetches

if TYPE_CHECKING:
    from .fetch import FetchResult

log = logging.getLogger(__name__)

CACHE_DIR_ENV = f"{TOOL.upper()}_CACHE_DIR"
TTL_ENV = f"{TOOL.upper()}_CACHE_TTL_DAYS"
MAX_GB_ENV = f"{TOOL.upper()}_CACHE_MAX_GB"
DEFAULT_TTL_DAYS = 90
CLEANUP_EVERY = timedelta(days=1)
CLEANUP_MARKER = ".last-cleanup"
ORPHAN_AGE = timedelta(days=1)
# what a stored file keeps of the response (besides its headers and the Markdown), as FetchResult names it
RESPONSE_FIELDS = ("final_url", "status", "redirects", "content_type", "bytes", "refresh_url", "rendered")
_BATCH = 1000  # rows deleted per statement in the cleanup


def now() -> datetime:
    return datetime.now(UTC)


def cache_dir() -> Path:
    if path := os.environ.get(CACHE_DIR_ENV):
        return Path(path).expanduser()
    return platformdirs.user_cache_path(TOOL, appauthor=False) / "fetch"


def _env_number(name: str) -> float | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        number = -1.0
    if number < 0:
        raise InvalidArguments(f"{name} must be a number, 0 or more (it is '{value}').")
    return number


def term() -> timedelta:
    """How long a stored fetch lives: SPIDER_CACHE_TTL_DAYS."""
    days = _env_number(TTL_ENV)
    return timedelta(days=DEFAULT_TTL_DAYS if days is None else days)


def max_bytes() -> float | None:
    """The size limit of the stored files: SPIDER_CACHE_MAX_GB, None — no limit."""
    gigabytes = _env_number(MAX_GB_ENV)
    return None if gigabytes is None else gigabytes * 10**9


def _utc(value: datetime) -> datetime:
    """A time read back from the database: SQLite gives it without a zone (it was written in UTC)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class StoredFetch:
    response: dict  # RESPONSE_FIELDS and `headers`
    markdown: str | None
    source: bytes  # the page source that was parsed
    content_hash: str
    cache_key: str
    fetched_at: datetime


class FetchStore:
    """The page storage for one run in one fetch mode (`rendered`: --render or not)."""

    def __init__(self, engine: sa.Engine, directory: Path, *, rendered: bool, max_age: timedelta) -> None:
        self.engine, self.directory = engine, directory
        self.rendered, self.max_age = rendered, max_age
        self._compressor = zstandard.ZstdCompressor(level=3)

    @classmethod
    def open(cls, *, rendered: bool, max_age_days: float | None = None) -> FetchStore:
        """The storage, cleaned up if a day has passed; a stored fetch older than `max_age_days` (default: the term)
        is a miss."""
        max_age = term() if max_age_days is None else timedelta(days=max_age_days)
        found = cls(storage.open_db(), cache_dir(), rendered=rendered, max_age=max_age)
        try:
            found.cleanup()
        except Exception as exc:  # the storage still works: the cleanup tries again tomorrow
            log.warning("page storage cleanup failed: %s", exc)
        return found

    def close(self) -> None:
        self.engine.dispose()

    def _path(self, cache_key: str) -> Path:
        return self.directory / cache_key[:2] / f"{cache_key}.zst"

    def _delete_files(self, cache_keys: list[str]) -> None:
        for cache_key in cache_keys:
            self._path(cache_key).unlink(missing_ok=True)

    def lookup(self, url_key: str) -> StoredFetch | None:
        """The stored fetch of this URL younger than the max age, if its file is readable."""
        query = sa.select(fetches.c.cache_key, fetches.c.content_hash, fetches.c.fetched_at).where(
            fetches.c.url_key == url_key,
            fetches.c.rendered == self.rendered,
            fetches.c.fetched_at > now() - self.max_age,
        )
        with self.engine.connect() as conn:
            row = conn.execute(query).first()
        if row is None:
            return None
        try:
            raw = zstandard.ZstdDecompressor().decompress(self._path(row.cache_key).read_bytes())
            header, source = raw.split(b"\n", 1)
            data = json.loads(header)
        except (OSError, ValueError, zstandard.ZstdError) as exc:  # gone or damaged: fetched again
            log.info("stored fetch %s is unreadable: %s", row.cache_key, exc)
            return None
        markdown = data.pop("markdown")
        return StoredFetch(data, markdown, source, row.content_hash, row.cache_key, _utc(row.fetched_at))

    def save(self, result: FetchResult, headers: dict, source: bytes, markdown: str | None) -> None:
        """Store a live fetch (its file, then its row), replacing this URL's stored fetch; sets `cache_key`,
        `content_hash` and `fetched_at` (the stored time) on `result`."""
        fetched_at = now()
        cache_key = secrets.token_hex(16)
        header = {name: getattr(result, name) for name in RESPONSE_FIELDS} | {"headers": headers, "markdown": markdown}
        blob = self._compressor.compress(json.dumps(header, ensure_ascii=False).encode() + b"\n" + source)
        path = self._path(cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        content_hash = hashlib.sha256(source).hexdigest()
        row = {
            "url": result.url, "url_key": result.url_key, "domain_key": result.domain_key, "rendered": self.rendered,
            "final_url": result.final_url, "status": result.status, "content_hash": content_hash,
            "cache_key": cache_key, "fetched_at": fetched_at, "expires_at": fetched_at + term(), "bytes": len(blob),
        }  # fmt: skip
        mine = (fetches.c.url_key == result.url_key) & (fetches.c.rendered == self.rendered)
        try:
            with self.engine.begin() as conn:
                replaced = conn.execute(sa.delete(fetches).where(mine).returning(fetches.c.cache_key)).scalars().all()
                # another run may have stored this URL since the delete: its row is replaced, not a failure
                conn.execute(storage.insert_or_replace(conn, fetches), row)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        self._delete_files(list(replaced))
        result.cache_key, result.content_hash, result.fetched_at = cache_key, content_hash, fetched_at.isoformat()

    def cleanup(self) -> None:
        """Once a day: delete expired fetches, then the oldest while the files are over SPIDER_CACHE_MAX_GB, then the
        old files without a row."""
        current = now()
        marker = self.directory / CLEANUP_MARKER
        try:
            last = datetime.fromisoformat(marker.read_text().strip())
        except OSError, ValueError:
            last = None
        if last is not None and current - last < CLEANUP_EVERY:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        marker.write_text(current.isoformat())
        with self.engine.begin() as conn:
            expired = conn.execute(sa.select(fetches.c.id).where(fetches.c.expires_at < current)).scalars().all()
        self._drop(list(expired))
        limit = max_bytes()
        if limit is not None:
            self._drop(self._oldest_over(limit))
        self._delete_orphans(current)

    def _oldest_over(self, limit: float) -> list[int]:
        """Ids of the oldest fetches to delete so that the rest fit `limit` bytes."""
        with self.engine.connect() as conn:
            total = conn.execute(sa.select(sa.func.coalesce(sa.func.sum(fetches.c.bytes), 0))).scalar_one()
            ids: list[int] = []
            rows = conn.execute(sa.select(fetches.c.id, fetches.c.bytes).order_by(fetches.c.fetched_at))
            for id_, size in rows:
                if total <= limit:
                    break
                ids.append(id_)
                total -= size
            rows.close()
        return ids

    def _delete_orphans(self, current: datetime) -> None:
        with self.engine.connect() as conn:
            known = set(conn.execute(sa.select(fetches.c.cache_key)).scalars())
        for path in self.directory.glob("*/*.zst"):
            try:
                old = current - datetime.fromtimestamp(path.stat().st_mtime, UTC) > ORPHAN_AGE
            except OSError:  # deleted by another run meanwhile
                continue
            if old and path.stem not in known:
                path.unlink(missing_ok=True)

    def _drop(self, ids: list[int]) -> None:
        cache_keys: list[str] = []
        with self.engine.begin() as conn:
            for chunk in itertools.batched(ids, _BATCH, strict=False):
                delete = sa.delete(fetches).where(fetches.c.id.in_(chunk)).returning(fetches.c.cache_key)
                cache_keys += conn.execute(delete).scalars().all()
        self._delete_files(cache_keys)
