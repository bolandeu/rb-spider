---
id: SPIDER-007
title: 'Proxy: no change-IP call when the proxy is remembered dead'
status: publish
attempts: 0
blocked: true
blocked_reason: gate_no_answer
phase: null
tests_hash: null
publish_stage: gate
created_by: architect
approved_by: architect
worker: claude-code
type: bugfix
owns_paths:
- src/rb_spider/core/proxy.py
- src/rb_spider/core/proxy_state.py
- tests/
test_paths:
- tests/test_proxy.py
docs: none
tools: []
worker_args: null
class: standard
decision: false
visual: null
depends_on: []
budget_usd: null
epic: null
spec_refs: []
checks:
- uv run --extra render --extra curl --extra near --extra structured --extra sitemaps
  --extra xpath --extra postgres --extra gsc pytest -q
- uv run ruff check
- uv run ruff format --check .
- uv run ty check
- gitleaks git --redact --no-banner .
resident: null
tool: null
pr: null
translation: Если прокси записан мёртвым, не вызывать смену IP в каждом запуске —
  сразу по proxy_fallback; смена IP только после новой проверки.
---

Defect of SPIDER-005 (v0.8.0). `open_proxies` in `src/rb_spider/core/proxy.py` (around line 333) calls `IpChanger.renew()` when all addresses fail, also when every failure comes from the remembered state (`proxy_state.fresh`, message 'remembered from …'). So every run within `crawl.proxy_state_ttl_s` calls the provider's change-IP links again. Seen live 2026-10-28 with a dead mobile proxy: 3 change-IP calls in every run, the provider answers 'Already change IP, please wait'. With a live paid proxy this would change the IP on every run for nothing.

Fix: when every failing address is known dead from the fresh state, do not change IP; go straight to `crawl.proxy_fallback`. Change IP only after a new check in this run found the addresses dead. The one stderr line about the proxy going off (SPIDER-006) stays one per run.

Tests first (red), then code. A fake test secret goes into `.gitleaks.toml` allowlist only as an exact string; better use a value gitleaks does not flag.

## Acceptance

- Given a dead fake proxy with change-IP links and proxy_state_ttl_s=600, When fetch runs twice, Then the first run calls change-IP once and the second run makes zero change-IP calls and zero proxy connections. [check: tests/test_proxy.py]
- Given a remembered-dead entry older than proxy_state_ttl_s, When fetch runs, Then the proxy is checked again and change-IP is called once. [check: tests/test_proxy.py]

## How to test

Integration with the polygon fake proxy and a fake change-IP provider that counts calls; tampered checked_at for the TTL.

## Basis

core/proxy.py open_proxies and its check loop; proxy_state.fresh; the existing change-IP test in tests/test_proxy.py.

## Read first

- `src/rb_spider/core/proxy.py`
- `src/rb_spider/core/proxy_state.py`

## Out of scope

- Other proxy behaviour; IpChanger during a crawl on blocked answers.
