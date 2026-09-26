"""Enrichers: plugins that add metrics to a crawl's URLs — search clicks, positions, speed scores…

A plugin is any installed package that declares an entry point in the `rb_spider.enrichers` group:

    [project.entry-points."rb_spider.enrichers"]
    gsc = "my_package.gsc:GscEnricher"

The object it names — a class (created without arguments) or an instance — has a `description`
and `enrich(crawl) -> Iterable[Metric]`. `spider enrich` hands it the crawl (`CrawlInfo`: id,
project, start URL and a stream of the site's URLs) and stores what it yields in `url_metrics`
under the entry point's name, replacing that plugin's earlier metrics for the crawl. Metrics are
written in batches as they come, so a plugin may yield millions of them. A metric's URL doesn't
have to be one the crawl found (a URL search engines know but links don't lead to is a finding too).

Secrets a plugin needs are its own business — the convention is spider's keychain
(`rb_spider.credentials.manager`), never the project config.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Any, Protocol

import sqlalchemy as sa

from . import storage
from .errors import InvalidArguments, ProviderError

GROUP = "rb_spider.enrichers"
BATCH = 1000
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Metric:
    """One value for one URL: a number (`value`), a text (`text`), or both."""

    url: str
    name: str
    value: float | None = None
    text: str | None = None


@dataclass(frozen=True)
class CrawlInfo:
    """The crawl an enricher works on."""

    crawl_id: int
    project: str
    start_url: str
    _engine: sa.Engine

    def urls(self) -> Iterator[str]:
        """The site's own URLs of the crawl (not other sites'), streamed in URL order."""
        pages = storage.pages
        query = (
            sa.select(pages.c.url)
            .where(pages.c.crawl_id == self.crawl_id, sa.not_(sa.func.coalesce(pages.c.external, False)))
            .order_by(pages.c.url)
        )
        with self._engine.connect() as conn:
            for (url,) in conn.execution_options(yield_per=BATCH).execute(query):
                yield url


class Enricher(Protocol):
    description: str

    def enrich(self, crawl: CrawlInfo) -> Iterable[Metric]: ...


@dataclass
class Plugin:
    name: str  # the entry point's name: the `source` of its metrics
    target: str  # "module:attribute"
    description: str
    error: str | None  # why it couldn't be loaded
    enricher: Enricher | None


def _load(entry: EntryPoint) -> Plugin:
    try:
        obj: Any = entry.load()
        enricher = obj() if isinstance(obj, type) else obj
        if not callable(getattr(enricher, "enrich", None)):
            raise TypeError("no enrich(crawl) method")
        return Plugin(entry.name, entry.value, str(getattr(enricher, "description", "")), None, enricher)
    except Exception as exc:  # a broken plugin must not break spider: it's listed with the reason
        return Plugin(entry.name, entry.value, "", f"{type(exc).__name__}: {exc}", None)


def discover() -> list[Plugin]:
    """Every installed enricher, by name."""
    return sorted((_load(entry) for entry in entry_points(group=GROUP)), key=lambda p: p.name)


def _checked(metric: Any, plugin: str) -> tuple[str, str, float | None, str | None]:
    if not isinstance(metric, Metric) or not metric.url or not metric.name:
        raise ProviderError(plugin, f"yielded {metric!r}, expected Metric(url, name, value, text)")
    value = metric.value
    if value is not None and (not isinstance(value, int | float) or not math.isfinite(value)):
        raise ProviderError(plugin, f"metric {metric.name!r} of {metric.url} has a non-numeric value {value!r}")
    return metric.url, metric.name, float(value) if value is not None else None, metric.text


def run(engine: sa.Engine, crawl_id: int, names: list[str] | None = None) -> dict[str, int]:
    """Run enrichers (all loadable ones, or the named) on a crawl; returns metrics stored per plugin."""
    plugins = {p.name: p for p in discover()}
    unknown = [n for n in names or [] if n not in plugins]
    if unknown:
        known = ", ".join(plugins) or "none installed"
        raise InvalidArguments(f"Unknown enricher: {', '.join(unknown)}. Installed: {known}.")
    chosen = [plugins[n] for n in names] if names else [p for p in plugins.values() if p.enricher]
    broken = [p for p in chosen if p.enricher is None]
    if broken:
        raise ProviderError(broken[0].name, f"cannot be loaded ({broken[0].error})")
    row, _ = storage.get_crawl(engine, crawl_id)
    crawl = CrawlInfo(crawl_id, row.project, row.start_url, engine)
    return {plugin.name: _store(engine, crawl, plugin) for plugin in chosen}


def _store(engine: sa.Engine, crawl: CrawlInfo, plugin: Plugin) -> int:
    """One plugin's metrics replace its earlier ones for the crawl — in one transaction, so a failing
    plugin leaves the previous run's metrics intact."""
    enricher = plugin.enricher
    if enricher is None:
        raise ProviderError(plugin.name, f"cannot be loaded ({plugin.error})")
    metrics = storage.url_metrics
    insert = sa.insert(metrics).prefix_with("OR REPLACE")
    count = 0
    with engine.begin() as conn:
        conn.execute(sa.delete(metrics).where(metrics.c.crawl_id == crawl.crawl_id, metrics.c.source == plugin.name))
        batch: list[dict] = []
        try:
            for metric in enricher.enrich(crawl):
                url, name, value, text = _checked(metric, plugin.name)
                batch.append({"crawl_id": crawl.crawl_id, "url": url, "source": plugin.name, "name": name,
                              "value": value, "text": text})  # fmt: skip
                if len(batch) >= BATCH:
                    conn.execute(insert, batch)
                    count, batch = count + len(batch), []
        except ProviderError:
            raise
        except Exception as exc:  # the plugin's own failure (network, API, bug): name it, keep old metrics
            raise ProviderError(plugin.name, f"{type(exc).__name__}: {exc}") from exc
        if batch:
            conn.execute(insert, batch)
            count += len(batch)
    log.debug("enricher %s stored %d metrics", plugin.name, count)
    return count


def metrics_of(engine: sa.Engine, crawl_id: int, url: str) -> list[dict]:
    metrics = storage.url_metrics
    query = (
        sa.select(metrics.c.source, metrics.c.name, metrics.c.value, metrics.c.text)
        .where(metrics.c.crawl_id == crawl_id, metrics.c.url == url)
        .order_by(metrics.c.source, metrics.c.name)
    )
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(query).mappings()]
