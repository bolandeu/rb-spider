"""`spider lighthouse`: page speed and mobile audits by Lighthouse, run on this machine for a sample of a crawl's pages.

Speed problems are a template's, not a page's: the same scripts, styles and images load on every product card. So by
default only typical landing pages are measured — per template (a folder and a path depth: every /catalog/x/y is
one), the pages with the most inlinks, and the home page; explicit URLs or `--all` measure exactly those.

Lighthouse is Google's own (the engine of PageSpeed Insights), an npm package run as a command
(`lighthouse.command`); each page is one run, its JSON report parsed and every audit stored in `lighthouse_audits`.
`lighthouse.source = "psi"` asks PageSpeed Insights instead (through the sibling package gsc, which holds the key and
keeps to the API's limits): the same audits, run on Google's servers, plus the field data of real Chrome users
(CrUX) — stored beside them as `crux:<metric>` (the page) and `crux-origin:<metric>` (the whole site).
Lighthouse 12+ no longer checks text size or content width on phones: on mobile, spider measures those itself in a
browser at a phone's viewport, as Lighthouse did (`spider-content-width`, `spider-font-size`). The PageSpeed and
Mobile rules read the table; `analyze` keeps them, and a new run refreshes them.
"""

from __future__ import annotations

import heapq
import json
import logging
import os
import shlex
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import sqlalchemy as sa

from . import storage
from .errors import CliError, InvalidArguments
from .settings import LighthouseSettings, Settings
from .version import DIST_NAME

if TYPE_CHECKING:
    import gsc  # the `gsc` extra: imported where PageSpeed Insights is used

log = logging.getLogger(__name__)

MAX_ITEMS = 20  # an audit's resources kept per page
CATEGORIES = "performance,accessibility"  # accessibility: target-size
LEGIBLE_PX = 12  # Lighthouse's old font-size audit: text smaller than this is hard to read on a phone
LEGIBLE_SHARE = 0.6  # …and it failed when less than 60 % of the text was legible
PHONE_WIDTH, PHONE_HEIGHT = 412, 823  # the Moto G Power Lighthouse emulates

# the page as a phone shows it: wider than the screen? how much of its text is too small?
_MOBILE_JS = """(limit) => {
  let total = 0, small = 0;
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const text = walker.currentNode.textContent.trim();
    const el = walker.currentNode.parentElement;
    if (!text || !el) continue;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    total += text.length;
    if (parseFloat(style.fontSize) < limit) small += text.length;
  }
  return {width: document.documentElement.scrollWidth, viewport: window.innerWidth, total, small};
}"""


class LighthouseUnavailable(CliError):
    """The Lighthouse command can't be run."""

    def __init__(self, command: str, reason: str) -> None:
        super().__init__(
            "LIGHTHOUSE_UNAVAILABLE",
            f"Lighthouse can't run ({command}): {reason}.",
            action=(
                "Lighthouse needs Node.js (https://nodejs.org) and the npm package: npm install -g lighthouse. "
                'Or without installing: --set lighthouse.command="npx --yes lighthouse".'
            ),
            exit_code=1,
        )


class PageSpeedUnavailable(CliError):
    """`lighthouse.source = "psi"` without the `gsc` extra."""

    def __init__(self) -> None:
        super().__init__(
            "PAGESPEED_UNAVAILABLE",
            "PageSpeed Insights needs the gsc package, which is not installed.",
            action=(
                f'Install spider with the extra: uv tool install --reinstall "{DIST_NAME}[gsc] @ '
                'git+https://github.com/bolandeu/spider.git" (in a checkout: uv sync --extra gsc), '
                "or measure here: --source local."
            ),
            exit_code=1,
        )


def pagespeed_client() -> gsc.PageSpeed:
    """The PageSpeed Insights client of the gsc package (its key: `gsc auth login --provider pagespeed`); tests put
    a fake here."""
    try:
        import gsc
    except ImportError:
        raise PageSpeedUnavailable from None
    return gsc.PageSpeed()


def available(settings: LighthouseSettings) -> str | None:
    """The command's executable if it can be found, else None (for `spider doctor`)."""
    parts = shlex.split(settings.command)
    return shutil.which(parts[0]) if parts else None


def template(url: str) -> tuple[str, int]:
    """A page's template: its first folder (for pages deeper than one level) and its path depth."""
    segments = [s for s in urlsplit(url).path.split("/") if s]
    return (segments[0] if len(segments) > 1 else "", len(segments))


def sample(engine: sa.Engine, crawl_id: int, per_template: int, max_pages: int) -> list[str]:
    """Typical landing pages: per template the pages with the most inlinks, the home page first, the biggest
    templates next. Streams the crawl's pages; only `per_template` pages per template are held."""
    best: dict[tuple[str, int], list[tuple[int, str]]] = {}
    sizes: dict[tuple[str, int], int] = {}
    query = sa.text(
        "SELECT url, coalesce(unique_inlinks, 0) FROM spider_pages WHERE crawl_id = :c AND NOT coalesce(external, FALSE)"
        " AND parsed AND status_code = 200 AND content_type LIKE '%html%' AND coalesce(indexable, TRUE)"
    )
    with engine.connect() as conn:
        for url, inlinks in storage.streamed(conn, 2000).execute(query, {"c": crawl_id}):
            key = template(url)
            sizes[key] = sizes.get(key, 0) + 1
            heap = best.setdefault(key, [])
            if len(heap) < per_template:
                heapq.heappush(heap, (inlinks, url))
            elif inlinks > heap[0][0]:
                heapq.heapreplace(heap, (inlinks, url))
    ordered = sorted(best, key=lambda k: (k != ("", 0), -sizes[k], k))  # home, then the biggest templates
    return [url for key in ordered for _, url in sorted(best[key], reverse=True)][:max_pages]


@dataclass
class PageResult:
    url: str
    ok: bool
    error: str | None = None
    performance: float | None = None
    metrics: dict[str, float | None] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)  # audits that failed (score < 0.9)


_METRICS = {"lcp_ms": "largest-contentful-paint", "fcp_ms": "first-contentful-paint", "cls": "cumulative-layout-shift",
            "tbt_ms": "total-blocking-time", "speed_index_ms": "speed-index"}  # fmt: skip


def _chrome(settings: Settings) -> str | None:
    """Chrome for Lighthouse: lighthouse.chrome, crawl.render_browser, a full Chromium from Playwright's cache."""
    from .render import cached_browsers

    explicit = settings.lighthouse.chrome or settings.crawl.render_browser
    if explicit:
        return explicit
    full = [p for p in cached_browsers() if "headless" not in str(p)]
    return str(full[0]) if full else None


def run(engine: sa.Engine, crawl_id: int, urls: Iterable[str], settings: Settings) -> Iterator[PageResult]:
    """Measure each URL, replacing what an earlier run stored for it (same strategy); yields a result per page."""
    lh = settings.lighthouse
    chrome = _chrome(settings)
    measured = _psi(pagespeed_client(), urls, lh) if lh.source == "psi" else _local(urls, lh, chrome)
    from .issues import CHECKED_AUDITS  # issues imports much of core: only when measuring

    checked = set(CHECKED_AUDITS)
    mobile = _MobileMeasure(chrome) if lh.strategy == "mobile" else None
    try:
        for url, result in measured:
            rows = result.pop("rows", [])
            if mobile is not None and result["ok"]:
                rows += mobile.measure(url)
            page = PageResult(url, **result)
            page.failed = [r["audit"] for r in rows if r["audit"] in checked and r["score"] is not None
                           and r["score"] < 0.9]  # fmt: skip
            _store(engine, crawl_id, url, lh.strategy, lh.source, rows)
            yield page
    finally:
        if mobile is not None:
            mobile.close()


def _local(urls: Iterable[str], lh: LighthouseSettings, chrome: str | None) -> Iterator[tuple[str, dict]]:
    """Lighthouse on this machine, a page at a time; a missing command fails here, before any page."""
    command = shlex.split(lh.command)
    if not command or shutil.which(command[0]) is None:
        raise LighthouseUnavailable(lh.command, "the command isn't found")
    env = dict(os.environ)
    if chrome:
        env["CHROME_PATH"] = chrome
    return ((url, _one(command, url, lh, env)) for url in urls)


def _psi(client: gsc.PageSpeed, urls: Iterable[str], lh: LighthouseSettings) -> Iterator[tuple[str, dict]]:
    """PageSpeed Insights, `psi_concurrency` pages at a time; results come as they are ready, not in order."""
    import gsc

    try:
        for found in client.analyze_many(urls, lh.strategy, CATEGORIES.split(","), concurrency=lh.psi_concurrency):
            yield found.url, _from_psi(found)
    except gsc.CliError as exc:  # no key, a rejected key, the daily quota: stops the run, what was measured stays
        raise CliError(exc.code, exc.message, action=exc.action, exit_code=exc.exit_code) from exc


_CRUX_SCORES = {"FAST": 1.0, "AVERAGE": 0.5, "SLOW": 0.0}  # CrUX's category of a metric: good / needs work / poor
_CRUX_METRICS = ("lcp", "inp", "cls", "fcp", "ttfb")


def _from_psi(found: gsc.PageSpeedResult | gsc.PageSpeedError) -> dict:
    """A PageSpeed Insights result as the rows a local run stores, plus the CrUX field data."""
    import gsc

    if isinstance(found, gsc.PageSpeedError):  # this page failed, the others go on
        return {"ok": False, "error": f"{found.code}: {found.message}"[:300]}
    if found.runtime_error:
        return {"ok": False, "error": found.runtime_error[:300]}
    rows = [_audit_row(a.id, a.score, a.numeric_value, a.display_value, a.details) for a in found.audits]
    rows += [_category_row(name, score) for name, score in found.scores.items()]
    for scope, crux in (("crux", found.crux_url), ("crux-origin", found.crux_origin)):
        if crux is None:
            continue
        rows.append({"audit": f"{scope}:overall", "score": _CRUX_SCORES.get(crux.overall_category or ""),
                     "value": None, "display": crux.overall_category, "items": None})  # fmt: skip
        for name in _CRUX_METRICS:
            metric = getattr(crux, name)
            if metric is None:
                continue
            share = f", хорошо у {round(100 * metric.good)} %" if metric.good is not None else ""
            rows.append({"audit": f"{scope}:{name}", "score": _CRUX_SCORES.get(metric.category or ""),
                         "value": metric.value, "display": f"{metric.category or '—'}{share}", "items": None})  # fmt: skip
    return _summary(rows)


def _one(command: list[str], url: str, lh: LighthouseSettings, env: dict[str, str]) -> dict:
    """One Lighthouse run: its audits as table rows, or why it failed."""
    args = [*command, url, "--output=json", "--output-path=stdout", "--quiet", f"--only-categories={CATEGORIES}",
            "--chrome-flags=--headless=new --no-first-run --no-default-browser-check"]  # fmt: skip
    if lh.strategy == "desktop":
        args.append("--preset=desktop")
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=lh.timeout_s, env=env, check=False)  # noqa: S603 — the configured command
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {lh.timeout_s} s"}
    except OSError as exc:
        raise LighthouseUnavailable(lh.command, str(exc)) from exc
    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError:
        tail = (done.stderr or done.stdout).strip().splitlines()[-1:] or [f"exit code {done.returncode}"]
        return {"ok": False, "error": tail[0][:300]}
    if report.get("runtimeError", {}).get("code"):
        return {
            "ok": False,
            "error": f"{report['runtimeError']['code']}: {report['runtimeError'].get('message', '')}"[:300],
        }
    rows = [
        _audit_row(
            a_id, a.get("score"), a.get("numericValue"), a.get("displayValue"), (a.get("details") or {}).get("items")
        )
        for a_id, a in report.get("audits", {}).items()
    ]
    rows += [_category_row(name, category.get("score")) for name, category in report.get("categories", {}).items()]
    return _summary(rows)


def _summary(rows: list[dict]) -> dict:
    audits = {r["audit"]: r for r in rows}
    performance = audits.get("category:performance", {}).get("score")
    metrics = {name: audits.get(audit, {}).get("value") for name, audit in _METRICS.items()}
    return {"ok": True, "rows": rows, "performance": performance, "metrics": metrics}


def _category_row(name: str, score: object) -> dict:
    return {"audit": f"category:{name}", "score": float(score) if isinstance(score, int | float) else None,
            "value": None, "display": None, "items": None}  # fmt: skip


def _audit_row(audit_id: str, score: object, value: object, display: str | None, found: object) -> dict:
    items = []
    for item in (found if isinstance(found, list) else [])[:MAX_ITEMS]:  # a tree (network chains) isn't kept
        if isinstance(item, dict):
            kept = {k: item[k] for k in ("url", "wastedBytes", "wastedMs", "totalBytes", "node") if k in item}
            if isinstance(kept.get("node"), dict):  # an element: its selector is enough
                kept["node"] = kept["node"].get("selector") or kept["node"].get("snippet")
            if kept:
                items.append(kept)
    return {
        "audit": audit_id,
        "score": float(score) if isinstance(score, int | float) else None,
        "value": float(value) if isinstance(value, int | float) else None,
        "display": display,
        "items": json.dumps(items, ensure_ascii=False) if items else None,
    }


def _store(engine: sa.Engine, crawl_id: int, url: str, strategy: str, source: str, rows: list[dict]) -> None:
    table = storage.lighthouse_audits
    with engine.begin() as conn:
        conn.execute(sa.delete(table).where(table.c.crawl_id == crawl_id, table.c.url == url,
                                            table.c.strategy == strategy))  # fmt: skip
        if rows:
            conn.execute(
                sa.insert(table),
                [{"crawl_id": crawl_id, "url": url, "strategy": strategy, "source": source, **r} for r in rows],
            )


class _MobileMeasure:
    """The two phone checks Lighthouse dropped, measured in one browser kept open for the whole run."""

    def __init__(self, chrome: str | None) -> None:
        self.browser = self._pw = None
        try:
            from playwright.sync_api import sync_playwright  # the `render` extra
        except ImportError:
            log.warning("mobile measures skipped: Playwright (rb-spider[render]) is not installed")
            return
        try:
            self._pw = sync_playwright().start()
            self.browser = self._pw.chromium.launch(headless=True, **({"executable_path": chrome} if chrome else {}))
        except Exception as exc:  # no browser: the Lighthouse audits still count
            log.warning("mobile measures skipped: %s", str(exc).splitlines()[0] if str(exc) else type(exc).__name__)
            self.close()

    def measure(self, url: str) -> list[dict]:
        if self.browser is None:
            return []
        context = self.browser.new_context(
            viewport={"width": PHONE_WIDTH, "height": PHONE_HEIGHT},
            is_mobile=True,
            has_touch=True,
            device_scale_factor=1.75,
        )
        try:
            page = context.new_page()
            page.goto(url, wait_until="load", timeout=60000)
            found = page.evaluate(_MOBILE_JS, LEGIBLE_PX)
        except Exception as exc:  # a page that won't load: no measure rather than a wrong one
            log.warning("mobile measure of %s failed: %s", url, str(exc).splitlines()[0] if str(exc) else exc)
            return []
        finally:
            context.close()
        wide = found["width"] > found["viewport"]
        legible = 1 - found["small"] / found["total"] if found["total"] else 1.0
        return [
            {"audit": "spider-content-width", "score": 0.0 if wide else 1.0, "value": float(found["width"]),
             "display": f"{found['width']} px при экране {found['viewport']} px", "items": None},
            {"audit": "spider-font-size", "score": 1.0 if legible >= LEGIBLE_SHARE else 0.0, "value": legible,
             "display": f"{round(100 * (1 - legible))} % текста мельче {LEGIBLE_PX} px", "items": None},
        ]  # fmt: skip

    def close(self) -> None:
        if self.browser is not None:
            self.browser.close()
            self.browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None


def pages_to_measure(engine: sa.Engine, crawl_id: int, urls: list[str], every: bool, settings: LighthouseSettings,
                     ) -> Iterator[str]:  # fmt: skip
    """The URLs given (they must be the crawl's HTML pages), every such page (read a batch at a time), or the
    sample."""
    if urls:
        with engine.connect() as conn:
            known = {row[0] for row in conn.execute(
                sa.text("SELECT url FROM spider_pages WHERE crawl_id = :c AND url IN :urls").bindparams(
                    sa.bindparam("urls", expanding=True)), {"c": crawl_id, "urls": urls})}  # fmt: skip
        missing = [u for u in urls if u not in known]
        if missing:
            raise InvalidArguments(f"Not in crawl #{crawl_id}: {', '.join(missing[:5])} — see 'spider urls'.")
        return iter(urls)
    if every:
        return _every(engine, crawl_id)
    return iter(sample(engine, crawl_id, settings.per_template, settings.max_pages))


def _every(engine: sa.Engine, crawl_id: int) -> Iterator[str]:
    query = sa.text(
        "SELECT url FROM spider_pages WHERE crawl_id = :c AND NOT coalesce(external, FALSE) AND parsed AND status_code = 200"
        " AND content_type LIKE '%html%' AND url > :after ORDER BY url LIMIT 500"
    )
    after = ""
    while True:
        with engine.connect() as conn:
            batch = [row[0] for row in conn.execute(query, {"c": crawl_id, "after": after})]
        if not batch:
            return
        yield from batch
        after = batch[-1]
