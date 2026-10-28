"""What spider remembers of each proxy address between runs (`crawl.proxy_state_ttl_s`): a cache, so deleting it only
costs one check.

One JSON file, `proxy-state.json`, in `SPIDER_CACHE_DIR` (default: the user cache dir). One entry per address, keyed by
a hash of the address without its password: `status` (alive | dead | null — the IP changed since), `checked_at`,
`reason` (the password scrubbed) and `ip_changes` (timestamps of the change-IP calls of the last 24 h). Written by the
start check, the in-run breaker, every change-IP call and `spider auth status --check`; read by the start check and
`spider doctor`. Runs at once never leave a half-written file: a write goes to a temp file that replaces the old one.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import platformdirs

from .._distribution import TOOL
from .fetch_store import CACHE_DIR_ENV

FILE_NAME = "proxy-state.json"
IP_CHANGES_KEPT = timedelta(hours=24)


def state_path() -> Path:
    base = Path(os.environ[CACHE_DIR_ENV]).expanduser() if os.environ.get(CACHE_DIR_ENV) else None
    return (base or platformdirs.user_cache_path(TOOL, appauthor=False)) / FILE_NAME


def display_address(url: str) -> str:
    """The address as people see it: scheme, user, host and port — never the password."""
    parts = urlsplit(url)
    user = f"{parts.username}@" if parts.username else ""
    return f"{parts.scheme}://{user}{parts.hostname}{f':{parts.port}' if parts.port else ''}"


def _key(url: str) -> str:
    return hashlib.sha256(display_address(url).encode()).hexdigest()[:16]


def _now() -> datetime:
    return datetime.now(UTC)


def _load() -> dict[str, dict]:
    try:
        data = json.loads(state_path().read_text())
    except OSError, ValueError:
        return {}  # missing or damaged: a cache, the next check writes it again
    return data if isinstance(data, dict) else {}


def _save(state: dict[str, dict]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{FILE_NAME}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as out:
            json.dump(state, out)
        os.replace(name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise


def _recent(stamps: list[str]) -> list[str]:
    since = _now() - IP_CHANGES_KEPT
    return [stamp for stamp in stamps if datetime.fromisoformat(stamp) >= since]


def entry(url: str) -> dict | None:
    """The remembered entry of `url`'s address, its IP changes of the last 24 h only; None — none."""
    found = _load().get(_key(url))
    return {**found, "ip_changes": _recent(found.get("ip_changes", []))} if found else None


def fresh(url: str, ttl_s: float) -> dict | None:
    """The entry of `url` when its check is younger than `ttl_s` and says alive or dead; None — check again.
    `ttl_s` = 0 turns the memory off."""
    found = entry(url)
    if ttl_s <= 0 or not found or found.get("status") not in ("alive", "dead") or not found.get("checked_at"):
        return None
    return found if _now() - datetime.fromisoformat(found["checked_at"]) < timedelta(seconds=ttl_s) else None


def record(url: str, problem: str | None) -> None:
    """The result of a check of `url`: `problem` is why it failed, None — it works. The password is scrubbed."""
    parts = urlsplit(url)
    reason = problem.replace(parts.password, "***") if problem and parts.password else problem
    state = _load()
    found = state.get(_key(url), {})
    state[_key(url)] = {"status": "alive" if problem is None else "dead", "checked_at": _now().isoformat(),
                        "reason": reason, "ip_changes": _recent(found.get("ip_changes", []))}  # fmt: skip
    _save(state)


def record_ip_change(urls: list[str]) -> None:
    """A change-IP call for the modem behind `urls`: the old verdict is void, the call goes on the list."""
    state, stamp = _load(), _now().isoformat()
    for url in urls:
        found = state.get(_key(url), {})
        state[_key(url)] = {**found, "status": None, "ip_changes": [*_recent(found.get("ip_changes", [])), stamp]}
    _save(state)
