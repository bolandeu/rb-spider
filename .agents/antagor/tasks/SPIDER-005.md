---
id: SPIDER-005
title: 'Proxy: state remembered between runs, auth status --check and doctor'
status: ideas
attempts: 0
blocked: false
blocked_reason: null
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: null
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
- src/rb_spider/providers/secrets.py
- src/rb_spider/commands/doctor.py
- src/rb_spider/commands/auth.py
test_paths:
- tests/test_proxy.py
- tests/test_auth.py
docs:
- docs/profiles.md
- docs/features.md
- README.md
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
translation: 'Состояние прокси между запусками (10 мин): мёртвый — сразу по proxy_fallback,
  живой — без проверки на старте; auth status --check реально проверяет прокси; doctor
  показывает состояние и смены IP.'
---

spider remembers the proxy state between runs, so repeated calls (Windmill calls `spider fetch` many times in a row) do not check a known proxy again; `auth status --check` and `doctor` show the real proxy state. Depends on the fast proxy check of the previous task (TCP check, proxy vs direct, change-IP before "dead").

## What to build

1. **Proxy state file** in the user cache dir (`platformdirs.user_cache_path("spider") / "proxy-state.json"`; a cache: deleting it only costs one check). One entry per proxy address, keyed by a hash of the address without the password: `status` (alive | dead), `checked_at`, `reason` (scrubbed), `ip_changes` (timestamps of change-IP calls of the last 24 h). Written by the start check, the in-run breaker, every change-IP call, and `auth status --check`. Concurrent writers (several runs at once) must not corrupt it: write a temp file and rename.
2. **Use it.** New key `crawl.proxy_state_ttl_s` (default 600). An entry younger than that: `dead` → skip the check, go straight to `crawl.proxy_fallback` (failover: the next address that is not known dead); `alive` → skip the start check (the in-run breaker still guards). Older or missing: check as now. `0` turns the memory off.
3. **`spider auth status --check`** for provider `proxy`: one TCP check and one request through each address of the resolved settings (`crawl.proxy_urls`, the project config and `--profile` as other commands resolve them), at most 10 s in total, the result written to the state file. `ok` only when an address answers; else `invalid` (or the status the Standard health shape uses for a failing secret) with the reason. Change it in the provider (`src/rb_spider/providers/secrets.py`, its `check`), not in `credentials/health.py`: the report shape is a contract (`tests/test_auth.py`).
4. **`spider doctor`**: a proxy entry when `crawl.proxy_urls` is set: each address (no password), state, `checked_at`, reason, change-IP calls in the last 24 h. From the state file, no network; `doctor` says how to check now (`spider auth status --check`).
5. Docstrings and `help=` updated; `docs/profiles.md` regenerated; `docs/features.md` line.

Template files stay untouched: `core/opencli.py`, `core/data_files.py`, `credentials/health.py` (cli-generator: the template is frozen; a local change conflicts on every update). Declare the state file in README, section of the page storage, one line.

## Tests

Polygon fake proxies (hang, refuse, alive); fake clock or tampered `checked_at` for the TTL; two runs in a row: the second does no check (count the fake proxy's connections). Tests first (red), then code. Run CLI output tests with `FORCE_COLOR=1` too.

## Acceptance

- Given a fake proxy that hangs and proxy_state_ttl_s=600, When spider fetch runs twice in a row, Then the second run makes no connection to the proxy and goes straight by proxy_fallback. [check: tests/test_proxy.py]
- Given a state entry older than proxy_state_ttl_s, When fetch runs, Then the proxy is checked again and the entry updated. [check: tests/test_proxy.py]
- Given a dead proxy in the settings, When spider --json auth status --check, Then provider proxy is not ok, has the reason, takes at most 10 s, and the report shape is unchanged. [check: tests/test_auth.py]
- Given a state file, When spider --json doctor, Then a proxy entry shows each address without the password, state, checked_at, reason and change-IP calls of 24 h, without network. [check: tests/test_proxy.py]

## How to test

Integration with polygon fake proxies counting connections; tampered checked_at for the TTL; auth and doctor via CliRunner --json.

## Basis

The start check and breaker of SPIDER-004 write the state; providers/secrets.py ProxySecret.check; doctor's existing proxy credential lines.

## Read first

- `src/rb_spider/core/proxy.py`
- `src/rb_spider/providers/secrets.py`
- `src/rb_spider/commands/doctor.py`

## Out of scope

- Changes to credentials/health.py, core/opencli.py, core/data_files.py (template, frozen); proxy_concurrency and via; a shared state across machines.
