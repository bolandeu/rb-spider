---
id: SPIDER-004
title: 'Proxy: a dead proxy found in seconds (TCP check, proxy vs direct, change IP,
  breaker)'
status: in_progress
attempts: 2
blocked: true
blocked_reason: no_progress
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: architect
worker: claude-code
type: bugfix
owns_paths:
- src/rb_spider/core/proxy.py
- src/rb_spider/core/fetch.py
- src/rb_spider/core/crawl.py
- src/rb_spider/core/settings.py
- src/rb_spider/commands/fetch.py
- src/rb_spider/commands/crawl.py
- src/rb_spider/commands/options.py
- src/rb_spider/core/fingerprint.py
- src/rb_spider/core/fetch_store.py
- src/rb_spider/fetch.py
- src/rb_spider/output/human.py
- src/rb_spider/output/__init__.py
- tests/
- docs/
- CONTEXT.md
- README.md
test_paths:
- tests/test_proxy.py
- tests/test_fetch.py
docs:
- docs/profiles.md
- docs/features.md
tools: []
worker_args: null
class: hard
decision: false
visual: null
depends_on: []
budget_usd: null
epic: null
spec_refs: []
checks:
- python3 scripts/check_command_docstrings.py
- uv run --extra render --extra curl --extra near --extra structured --extra sitemaps
  --extra xpath --extra postgres --extra gsc pytest -q
- uv run ruff check
- uv run ruff format --check .
- uv run ty check
resident: null
tool: null
pr: null
translation: 'Мёртвый прокси за секунды: TCP-проверка с коротким таймаутом, прокси
  против прямого запроса, смена IP перед «мёртв» с причиной от провайдера, предохранитель
  в обходе (3 ошибки, таймауты в счёт).'
---

A dead proxy costs seconds once per run, not `crawl.timeout_s` per URL. Seen live on 2026-10-28 with the Human's profile `mobile` (failover; HTTP entry `mproxy.site:25580` hangs on TCP connect, SOCKS5 entry rejects the login; the site answers directly in 0.4 s): `spider fetch` took 60 s for one URL and gave `error: TimeoutError`, exit 0; `spider crawl` with `crawl.max_urls=5` took 4 min 17 s and ended `status: finished`, `proxy_down: null`. Cause: `open_proxies` (`src/rb_spider/core/proxy.py:156`) treats a timeout through the proxy as the site's failure, so the hanging address "works"; the in-run counter (`crawl.proxy_max_failures`, 20) does not count timeouts either.

## What to build

1. **TCP check of the proxy itself.** impit 0.14.1 has one `timeout`, no connect timeout (checked: `impit.AsyncClient` signature). Before the request check, open a TCP connection to each proxy address (host:port) with a new key `crawl.proxy_connect_timeout_s` (default 5). No connection in time, refused, unresolved: that address fails at once.
2. **Proxy vs direct.** The check request through the proxy (robots.txt of the site, as now) and the same request directly run at the same time, both with timeout `min(crawl.timeout_s, 10)`. Through the proxy no answer (any error, a timeout included) and directly an answer: the proxy failed. Both fail: the site's problem, the proxy is not blamed (as now). The direct request only checks; its answer is not used as page data.
3. **Change the IP before "dead".** All addresses failed and `crawl.proxy_change_ip_urls` is set: call the change-IP links once (the existing `IpChanger` logic), wait until the proxy answers (poll, at most `crawl.proxy_change_ip_wait_s`), check again. Still failed: the provider's answer to the change-IP call (when it is not ok, e.g. not paid, bad key) goes into the error text, with the key scrubbed.
4. **In-run breaker.** During crawl and fetch, a request through the proxy that ends with a proxy failure or with a timeout without any answer counts. `crawl.proxy_max_failures` default goes 20 → 3. When the count reaches it, run the check of item 2 once (proxy vs direct for the current URL's site): proxy failed → the address is dead (failover: next address; none left: `crawl.proxy_fallback`); the site's problem → reset the count, go on. An answer through the proxy resets the count.
5. **Outcomes unchanged in form:** `proxy_fallback = stop` → `spider fetch` exits 5 `PROXY_UNAVAILABLE` (in a terminal it asks, as now); `spider crawl` stops with `proxy_down` set (resumable). `direct` → go on without the proxy, the warning on stderr as now.
6. Docstrings, `help=`, `description=` of the new and changed keys; `docs/profiles.md` regenerated (`SPIDER_UPDATE_SNAPSHOTS=1 uv run pytest`); `docs/features.md` line; `CONTEXT.md` only if a new term appears.
7. While in `tests/test_proxy.py`: `test_with_fallback_direct_a_dying_proxy_is_dropped_and_its_urls_fetched_again` failed once in CI (IDEA-365: `_proxy_errors` returned `['http://127.0.0.1:45629/missing']`, trace `ValueError: I/O operation on closed file` in `crawl.proxy_failed_on`). If your change touches that path, find the race and fix it; report what you found.

## Tests

Polygon fake proxies: one accepts TCP and never answers (hang), one refuses, one answers 407; the site answers directly. Short timeouts via settings so the suite stays fast. Measure wall time in the tests (bounds, not exact). Run the tests that check CLI output with `FORCE_COLOR=1` too (CI sets it). Tests first (red), then code.

## Acceptance

- Given the polygon site and a fake proxy that hangs on connect, When spider --json fetch runs 3 URLs with proxy_fallback=stop and no terminal, Then it exits 5 PROXY_UNAVAILABLE within proxy_connect_timeout_s plus a small margin, not 3 x timeout_s. [check: tests/test_proxy.py]
- Given the same with proxy_fallback=direct, When fetch runs 3 URLs, Then all 3 pages come directly with status 200 and the run takes about one check, not timeouts per URL. [check: tests/test_proxy.py]
- Given a crawl through a proxy that dies mid-run, When 3 requests through it end with no answer, Then spider checks proxy vs direct once and goes by proxy_fallback; crawl ends with proxy_down set when fallback=stop. [check: tests/test_proxy.py]
- Given a site that is down for everyone and a working proxy, When fetch runs, Then the proxy is not blamed: the URL has its error and the run goes on. [check: tests/test_proxy.py]
- Given change-IP links and a dead proxy, When all addresses fail, Then spider calls change-IP once, checks again, and the provider's non-ok answer is in the error text with the key scrubbed. [check: tests/test_proxy.py]

## How to test

Integration against the polygon aiohttp site and fake proxies (hang / refuse / 407 / alive / dies mid-run) with short timeouts in settings; wall time asserted as bounds.

## Basis

Reuse core/proxy.py open_proxies, proxy_failure, IpChanger, ProxyUnavailable; crawl's proxy_failed_on counter; existing fake proxies in tests/test_proxy.py.

## Read first

- `src/rb_spider/core/proxy.py`
- `tests/test_proxy.py`
- `docs/dev.md`

## Out of scope

- Proxy state memory between runs, auth status --check and doctor (next task); proxy_concurrency and the via field (another task); a direct-first proxy mode.

## Feedback

### Answer to question #1

> SPIDER-004: item 5 says outcomes stay unchanged in form (fallback=stop: run_crawl raises ProxyUnavailable, status interrupted, spider crawl exits 5 PROXY_UNAVAILABLE, no result JSON, so no proxy_down field). Acceptance 3 says 'crawl ends with proxy_down set when fallback=stop'; today proxy_down is set only with fallback=direct.
> Question: Which point wins for a crawl stopped by a dead proxy with fallback=stop?
> Options:
> 1. Item 5: keep the form; stop raises ProxyUnavailable (exit 5, status interrupted, resumable); the test checks that
> 2. Acceptance 3: return a result with status interrupted and proxy_down set, exit 0 with JSON
> Recommended: Item 5: keep the form; stop raises ProxyUnavailable (exit 5, status interrupted, resumable); the test checks that

Item 5 wins; acceptance 3 was my error. With fallback=stop keep today's form: run_crawl raises ProxyUnavailable, crawl status interrupted (resumable), spider crawl exits 5 PROXY_UNAVAILABLE, no result JSON. With fallback=direct: the crawl goes on and ends with proxy_down set. Test acceptance 3 that way: 3 requests with no answer -> one proxy-vs-direct check -> stop: exit 5 and status interrupted; direct: finished with proxy_down.

### Blocked: needs_scope (entries [{'n': 1, 'text': 'SPIDER-004: item 5 says outcomes stay unchanged in form (fallback=stop: run_crawl raises ProxyUnavailable, status interrupted, spider crawl exits 5 PROXY_UNAVAILABLE, no result JSON, so no proxy_down '}])

Item 5 wins; acceptance 3 was my error. With fallback=stop keep today's form: run_crawl raises ProxyUnavailable, crawl status interrupted (resumable), spider crawl exits 5 PROXY_UNAVAILABLE, no result JSON. With fallback=direct: the crawl goes on and ends with proxy_down set. Test acceptance 3 that way: 3 requests with no answer -> one proxy-vs-direct check -> stop: exit 5 and status interrupted; direct: finished with proxy_down.

### Attempt 1: file docstring

- src/rb_spider/core/crawl.py 964 lines > limit 800: split it by meaning (one capability, one module)
- src/rb_spider/core/settings.py 1242 lines > limit 800: split it by meaning (one capability, one module)

### Attempt 2: file docstring

- src/rb_spider/core/crawl.py 964 lines > limit 800: split it by meaning (one capability, one module)
- src/rb_spider/core/settings.py 1242 lines > limit 800: split it by meaning (one capability, one module)
