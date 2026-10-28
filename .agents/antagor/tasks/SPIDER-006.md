---
id: SPIDER-006
title: 'Proxy: proxy_concurrency limit, via field and one stderr signal'
status: publish
attempts: 0
blocked: false
blocked_reason: null
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: architect
worker: claude-code
type: feature
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
class: standard
decision: false
visual: null
depends_on:
- SPIDER-004
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
translation: Предел параллельности через прокси (proxy_concurrency, 5), поле via (proxy/direct/cache)
  в fetch --json, одна строка в stderr, когда прокси отключён.
---

A mobile proxy (one modem) does not hold 20 connections at once; an overloaded modem looks dead. And a consumer (Windmill) must see whether a page came through the proxy, directly, or from the page storage. Depends on the fast proxy check task.

## What to build

1. **`crawl.proxy_concurrency`** (default 5, `ge=1`): at most this many requests in flight through the proxy, in `spider crawl` and `spider fetch`. Requests without the proxy (after `proxy_fallback = direct`) and storage hits use `crawl.concurrency` / `--concurrency`. When the proxy goes off mid-run, the limit goes back to `crawl.concurrency` if the engine allows it; if Crawlee's pool cannot change its limit mid-run, keep the lower one and say so in the report.
2. **`via` in `spider fetch --json`**, per URL: `"proxy"`, `"direct"` or `"cache"` (a storage hit). A compatible addition; existing keys unchanged. Human output: mark `direct` when proxies are configured but off.
3. **Signal**: when the proxy goes off in a run (start check or breaker), one line on stderr in every mode (`--json` included): what failed and what spider does now (stops / goes direct). Exactly one line per run, not per URL.
4. Docstring and `help=` of `spider fetch` (the `via` key), `description=` of the new key, `docs/profiles.md` regenerated, `docs/features.md` line, help snapshots and `describe.json` regenerated.

## Tests

Polygon fake proxy that counts concurrent connections: never more than `proxy_concurrency`. `via` for the three cases. The stderr line appears once with 5 URLs. Tests first (red), then code. Run CLI output tests with `FORCE_COLOR=1` too.

## Acceptance

- Given a fake proxy counting concurrent connections and proxy_concurrency=2, When crawl and fetch run 10 URLs with concurrency 10, Then the proxy never sees more than 2 at once. [check: tests/test_proxy.py]
- Given fetch --json, When a page comes through the proxy, directly after fallback, or from the page storage, Then via is proxy, direct or cache. [check: tests/test_fetch.py]
- Given a dead proxy and proxy_fallback=direct, When fetch --json runs 5 URLs, Then stderr has exactly one line about the proxy going off. [check: tests/test_proxy.py]

## How to test

Integration with the polygon and a fake proxy that counts concurrent connections; CliRunner with separate stderr.

## Basis

fetch_stream semaphore, Crawlee concurrency settings in core/crawl.py, the warning in open_proxies.

## Read first

- `src/rb_spider/core/fetch.py`
- `src/rb_spider/core/crawl.py`

## Out of scope

- A via column in crawl tables; a direct-first proxy mode; proxy state memory.
