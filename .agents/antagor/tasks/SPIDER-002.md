---
id: SPIDER-002
title: 'Deps: filelock for GHSA-v4x8-3wr5-3wq8 and two more'
status: done
attempts: 1
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
- uv run --extra render --extra curl --extra near --extra structured --extra sitemaps
  --extra xpath --extra postgres --extra gsc pytest -q
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

## Feedback

### Attempt 1: checks failed

- `uv run pytest` (exit 1)

```
ERROR: Coverage failure: total of 84 is less than fail-under=90
E       AssertionError: Regex pattern did not match.
E         Expected regex: 'no file'
E         Actual message: 'The curl HTTP client needs curl-cffi, which is not installed.'
…
b_spider/migrations/versions/0031_lighthouse.py                12      2    83%   32-33
src/rb_spider/migrations/versions/0032_lighthouse_source.py         11      2    82%   21-22
src/rb_spider/migrations/versions/0033_spider_prefix.py             15      1    93%   101
src/rb_spider/migrations/versions/0034_v1_views.py                  12      2    83%   40-41
src/rb_spider/output/__init__.py                                   123      2    98%   100, 183
src/rb_spider/output/human.py                                      478    309    35%   41-56, 60-73, 77-87, 91-99, 103-108, 112-118, 122-123, 127-135, 139-143, 147-155, 159-165, 169-180, 184-193, 197-205, 209-219, 223-235, 239-250, 254, 269-280, 301-306, 329-336, 340-342, 346-356, 360-366, 370-374, 378-381, 401-414, 418-433, 441, 454-456, 460, 464-470, 474-483, 487-488, 492-495, 509-513, 517, 521-522, 555-557, 559-562, 572, 577-589, 600, 604-609, 613-617, 648-654, 659-664, 668, 672-674, 679-685, 689-690
src/rb_spider/providers/__init__.py                                  9      1    89%   28
src/rb_spider/providers/base.py                                     58      2    97%   84, 119
src/rb_spider/providers/http.py                                     63      1    98%   56
src/rb_spider/providers/secrets.py                                  47      7    85%   43, 52, 71-72, 75, 79, 83
----------------------------------------------------------------------------------------------
TOTAL                                                             9127   1464    84%

41 files skipped due to complete coverage.
FAIL Required test coverage of 90.0% not reached. Total coverage: 83.96%
--------------------------- snapshot report summary ----------------------------
85 snapshots passed.
=========================== short test summary info ============================
FAILED tests/test_crawl_settings.py::test_ca_bundle_needs_curl - AssertionErr...
====== 1 failed, 997 passed, 76 skipped, 13 warnings in 97.01s (0:01:37) =======
```

### Blocked: no_progress (head bb7112487f4b6a99debde6262442d3776718938c)

Checks changed: pytest now runs with the extras of the gate (gate_extras).
