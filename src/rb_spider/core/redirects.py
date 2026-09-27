"""The redirect report: every redirecting URL followed hop by hop to where it finally lands.

Screaming Frog's Reports → Redirects (All Redirects, Redirect Chains, Redirects to Errors). A hop is a
server 3xx or a client-side meta / HTTP Refresh. Built from the stored crawl — nothing is fetched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import sqlalchemy as sa

from . import storage
from .settings import ThresholdSettings

Kind = Literal["all", "chains", "errors"]


@dataclass
class Hop:
    url: str
    status_code: int | None  # None: never fetched (another host, or the crawl stopped first)
    type: str  # "3xx" | "meta" | "http" — how this URL sends the client on


@dataclass
class Redirect:
    url: str
    hops: list[Hop]  # the source and every redirecting URL after it
    final_url: str | None  # None when the chain loops
    final_status: int | None
    loop: bool

    @property
    def is_error(self) -> bool:
        """Lands on no response, a robots-blocked URL, 4xx or 5xx — or never lands (loop)."""
        return self.loop or self.final_status == 0 or (self.final_status or 0) >= 400


def _pages(
    conn: sa.Connection, crawl_id: int, canonicals: bool = False
) -> dict[str, tuple[int, str | None, str | None]]:
    """url -> (status, where it sends the client, how). `canonicals` — a canonical to another URL counts as a hop
    too (Redirect & Canonical Chains)."""
    p = storage.pages
    rows = conn.execute(
        sa.select(p.c.url, p.c.status_code, p.c.redirect_url, p.c.refresh_url, p.c.refresh_kind, p.c.canonical_url)
        .where(p.c.crawl_id == crawl_id)
        .where(sa.not_(sa.func.coalesce(p.c.external, False)))  # the site's own redirects
    )
    result = {}
    for url, status, redirect_url, refresh_url, refresh_kind, canonical in rows:
        if redirect_url:
            result[url] = (status, redirect_url, "3xx")
        elif refresh_url:
            result[url] = (status, refresh_url, refresh_kind)
        elif canonicals and canonical and canonical != url:
            result[url] = (status, canonical, "canonical")
        else:
            result[url] = (status, None, None)
    return result


def _trace(url: str, pages: dict) -> Redirect:
    hops: list[Hop] = []
    seen: set[str] = set()
    current: str | None = url
    while current is not None:
        status, target, kind = pages.get(current, (None, None, None))
        if current in seen:
            return Redirect(url, hops, None, None, loop=True)
        if target is None:
            return Redirect(url, hops, current, status, loop=False)
        seen.add(current)
        hops.append(Hop(current, status, kind))
        current = target
    raise AssertionError("unreachable")  # pragma: no cover


def report(
    engine: sa.Engine,
    crawl_id: int,
    kind: Kind = "all",
    thresholds: ThresholdSettings | None = None,
    canonicals: bool = False,
) -> list[Redirect]:
    """Redirecting URLs of a crawl, traced to their final URL; `kind` narrows to chains or errors. `canonicals` —
    canonicals are hops too, and a URL that only canonicalises starts a chain of its own."""
    thresholds = thresholds or ThresholdSettings()
    with engine.connect() as conn:
        pages = _pages(conn, crawl_id, canonicals)
    traced = [_trace(url, pages) for url in sorted(url for url, (_, target, _) in pages.items() if target)]
    if kind == "chains":
        return [r for r in traced if r.loop or len(r.hops) >= thresholds.redirect_chain_hops]
    if kind == "errors":
        return [r for r in traced if r.is_error]
    return traced
