---
id: SPIDER-002
title: 'Deps: filelock for GHSA-v4x8-3wr5-3wq8 and two more'
status: queue
attempts: 0
blocked: false
blocked_reason: null
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: human
worker: claude-code
type: chore
owns_paths:
- uv.lock
test_paths: []
docs: none
tools: []
worker_args: null
class: mechanical
decision: false
visual: null
depends_on: []
budget_usd: null
epic: null
spec_refs: []
checks:
- osv-scanner scan source --lockfile uv.lock
- uv run pytest
resident: null
tool: null
pr: null
translation: Обновить filelock в uv.lock, чтобы osv-scanner не находил уязвимостей
  (3 GHSA); тесты проходят.
---

osv-scanner flags filelock 4.0.3 in uv.lock: GHSA-567q-5qvw-pf92, GHSA-9vhv-jxww-xfm5, GHSA-v4x8-3wr5-3wq8 (fixed in 4.2.1). Run `uv lock --upgrade-package filelock`, then `uv run pytest`. No ignores, no osv config. If the fixed version is not reachable (a pin above it), do not work around it: report which package holds it back and stop (blocked).

## Acceptance

- Given uv.lock, When the gate's vulnerability audit runs (osv-scanner), Then osv-scanner reports none; the tests pass. [check: osv-scanner scan source --lockfile uv.lock]

## Out of scope

- Any other dependency upgrade; osv-scanner ignores or config; changes outside uv.lock.
