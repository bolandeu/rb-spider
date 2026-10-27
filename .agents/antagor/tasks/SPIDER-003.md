---
id: SPIDER-003
title: 'spider fetch: page storage (from_cache, url_key, cache_key, term)'
status: in_progress
attempts: 1
blocked: true
blocked_reason: needs_scope
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: architect
worker: claude-code
type: feature
owns_paths:
- src/rb_spider/core/fetch.py
- src/rb_spider/core/fetch_store.py
- src/rb_spider/commands/fetch.py
- src/rb_spider/fetch.py
- src/rb_spider/core/tables.py
- src/rb_spider/migrations/versions/
- src/rb_spider/core/data_files.py
- src/rb_spider/output/human.py
- tests/
- docs/
- CONTEXT.md
- src/rb_spider/cli.py
- src/rb_spider/core/db.py
- src/rb_spider/core/opencli.py
- src/rb_spider/core/storage.py
- src/rb_spider/output/__init__.py
- CODING_STANDARDS.md
- src/rb_spider/core/maintenance.py
test_paths:
- tests/test_fetch_store.py
- tests/test_fetch.py
- tests/test_db.py
docs:
- docs/spec.md
- docs/features.md
- CONTEXT.md
- docs/adr/0001-fetch-storage.md
- docs/adr/
tools: []
worker_args: null
class: hard
decision: true
visual: null
depends_on: []
budget_usd: null
epic: null
spec_refs: []
checks:
- python3 scripts/check_command_docstrings.py
- uv run --extra render --extra curl --extra near --extra structured --extra sitemaps
  --extra xpath --extra postgres --extra gsc pytest -q
- scripts/pg_test.sh -q --no-cov tests/test_db.py tests/test_fetch_store.py tests/test_data_management.py
- uv run ruff check
- uv run ty check
resident: null
tool: null
pr: null
translation: 'Хранилище страниц для spider fetch: повтор URL в пределах срока — из
  хранилища без запроса к сайту (from_cache); индекс — таблица cache.spider_fetches,
  тела — файлы zstd; в ответе url_key, domain_key, content_hash, cache_key, fetched_at;
  --fresh, --max-age; срок и лимит — env; SQLite и PostgreSQL.'
---

`spider fetch` gets a page storage. A repeat fetch of the same URL within the storage term comes from the storage and does not request the site. Consumer: marketer (Windmill script `spider_fetch`, task T346, card `/Users/bolandau/Work/marketer/tasks/S345-competitor-pages.md`). The Human decided the storage on 2026-10-02: `/Users/bolandau/Work/marketer/docs/tools.md`, section «Загрузка страниц». Follow it.

## Design (the Architect's decision; record it as ADR 0001 with the reasons)

1. **Index: an own table `spider_fetches`**, `info={"kind": "cache"}`, `schema=CACHE_SCHEMA` (PostgreSQL schema `cache`; on SQLite no schema). Not `spider_pages` and not the stored-HTML file of crawls. Reasons for the ADR: crawl tables live per crawl (`crawl_id`, cascade delete) and are `data`; a fetch has no crawl, has a term and is a `cache` (can be fetched again); the stored-HTML file is a local SQLite per crawl, it does not work as a shared index on the prod PostgreSQL; the Human's decision names `spider_fetches`.
2. **Columns**: `id` (surrogate PK), `url` (as asked, normalized), `url_key`, `domain_key` (rb-keys `norm_url` / `norm_domain` of the asked URL), `rendered` (bool: the fetch mode, `--render` or not), `final_url`, `status`, `content_hash`, `cache_key` (UNIQUE), `fetched_at`, `expires_at`, `bytes` (size of the stored file). Natural key UNIQUE (`url_key`, `rendered`): one row per URL and mode, a new fetch replaces the row. Index on `fetched_at` (cleanup). New hand-written migration `0036`, compatible with the previous release (expand only). `tables.py` and the migration agree (`tests/test_db.py`).
3. **Bodies: zstd files**, not in the database. Directory: env `SPIDER_CACHE_DIR`, default `platformdirs.user_cache_path("spider") / "fetch"` (Mac: `~/Library/Caches/spider/fetch`; prod sets `/data/cache/spider`). One file per stored fetch, named by `cache_key`, sharded by its first characters. The file holds the page source that was parsed (raw HTML, or the rendered DOM with `--render`), the response data (`final_url`, `status`, `redirects`, `content_type`, `headers`, `refresh_url`, `rendered`) and the clean Markdown of the main content. A replaced row: delete its old file (best effort; a missing file is not an error).
4. **`cache_key`**: opaque, random per stored fetch (a new fetch gives a new key). It is not a path. `content_hash`: SHA-256 hex of the stored page source bytes.
5. **Hit**: a row with the same (`url_key`, `rendered`), younger than the max age, and its file is readable. Rebuild the `FetchResult` from the file: run the same extraction as a live fetch (`seo`, and `links`, `resources`, `text`, `html` per `--include`); `markdown` from the file. Same output as a live fetch of the same source. A row without a readable file is a miss.
6. **What is stored**: a response with a status and an HTML content type, status below 500 and not 429. Not stored: no response (`error`), 5xx, 429, non-HTML. These are fetched every time.
7. **No request at all on a full hit**: open the HTTP client, the proxy check (`open_proxies`), the fingerprint preparation and the browser only at the first miss. A run where every URL is a hit makes zero network requests.
8. **Options of `spider fetch`**: storage is on by default. `--fresh`: ignore stored fetches, fetch every URL, store the new fetch. `--max-age <days>`: a stored fetch older than this is a miss (default: the term). Library `rb_spider.fetch` / `fetch_stream`: the same as keyword arguments; storage is off by default in the library (`store=False`) so existing library callers and tests do not write files.
9. **Term and limit — env, not code**: `SPIDER_CACHE_TTL_DAYS` (default 90; `expires_at` = `fetched_at` + term), `SPIDER_CACHE_MAX_GB` (default: no limit). **Cleanup** by spider itself at the start of `spider fetch` with storage on, at most once a day (a marker file in the cache directory): delete rows and files past `expires_at`; then, over the limit, delete the oldest until under it. Cleanup errors do not fail the fetch.
10. **`--json` per URL adds** `url_key`, `domain_key`, `content_hash`, `cache_key`, `fetched_at` (ISO 8601 UTC; on a hit the stored time), `from_cache` (bool). For a result that is not stored (error, 5xx, non-HTML): `url_key` and `domain_key` are present (null if the URL does not parse), `content_hash` and `cache_key` null, `from_cache` false. Existing keys keep their form (a compatible change). Human output: mark a hit (for example «из хранилища»).
11. **Concurrency**: two runs storing the same URL at once must not fail: `storage.insert_or_replace`, unique file names.

## Docs in the same work

- Docstring and `help=` of `spider fetch` (the `--json` keys, `--fresh`, `--max-age`, the env, where files live); help snapshots and `describe.json` regenerated.
- `docs/spec.md`: the decision in short with a link to the ADR. `docs/features.md`: a new `[x]` item for the fetch storage. `CONTEXT.md`: the term «Хранилище страниц» (what it is, words to avoid: «кэш fetch»).
- `core/data_files.py` or the describe data: declare the fetch files as `cache` if the describe contract allows a cache-dir entry; if not, say so in the report.
- `docs/adr/0001-fetch-storage.md` in the format of `docs/adr/README.md`.

## TDD

The test commits come before the code (red first). Put the red run output in the report. A changed existing test: name it with the reason. Tests use the polygon (aiohttp server in pytest) and count the requests the server receives.

## Report

What is inside, the red run, changed existing tests with reasons, the gate result, and what prod needs: `spider db upgrade` (migration 0036), schema `cache` with USAGE and CREATE for the spider role, env `SPIDER_CACHE_DIR`, `SPIDER_CACHE_TTL_DAYS`, `SPIDER_CACHE_MAX_GB`.

## Acceptance

- Given the polygon and storage on, When spider --json fetch runs the same 3 URLs twice, Then the second run has from_cache true for each, the same content_hash and cache_key, and the polygon gets zero requests (no proxy check either). [check: tests/test_fetch_store.py]
- Given a stored fetch, When spider fetch --fresh or --max-age shorter than its age, Then the site is requested again, from_cache false, a new cache_key, the old file is deleted. [check: tests/test_fetch_store.py]
- Given any fetch, When --json, Then each object has url_key and domain_key (rb-keys), content_hash, cache_key, fetched_at, from_cache; a dead URL is a line with error and from_cache false, not a failure. [check: tests/test_fetch_store.py]
- Given a stored file, When it is read back, Then it is zstd-compressed and holds the HTML and the Markdown; rows past expires_at and over SPIDER_CACHE_MAX_GB are deleted by the daily cleanup, files too. [check: tests/test_fetch_store.py]
- Given SQLite and PostgreSQL, When migrated, Then spider_fetches exists (cache schema on PostgreSQL) and matches tables.py; storage works on both. [check: tests/test_db.py]

## How to test

Integration via CLI (CliRunner) against the polygon aiohttp server with a request counter; SPIDER_CACHE_DIR and SPIDER_DB_PATH in tmp_path; PostgreSQL via scripts/pg_test.sh; cleanup with a fake clock / tampered fetched_at.

## Basis

Reuse core/fetch.py Fetcher._read for extraction, storage.insert_or_replace, db.py open/migrate and CACHE_SCHEMA handling, zstandard as in storage.py, rb_keys norm_url/norm_domain as in migration 0035.

## Read first

- `src/rb_spider/core/fetch.py`
- `src/rb_spider/core/tables.py`
- `src/rb_spider/core/db.py`
- `docs/dev.md`
- `scripts/pg_test.sh`

## Out of scope

- Jobs (jobs start), --urls-file JSONL, S3 storage, trafilatura, summaries, a v1 view for Directus, storing non-HTML bodies, changes to crawl storage.

## Feedback

### Attempt 1: checks failed

- `scripts/pg_test.sh -q tests/test_db.py tests/test_fetch_store.py` (exit 1)

```
ERROR: Coverage failure: total of 50 is less than fail-under=90
…
            12      2    83%   40-41
src/rb_spider/migrations/versions/0035_shared_keys.py               43     13    70%   48-51, 59-63, 79-86
src/rb_spider/migrations/versions/0036_fetch_storage.py             14      1    93%   46
src/rb_spider/output/__init__.py                                   123     43    65%   98-101, 135-136, 144, 149-154, 160-161, 173-184, 191-193, 217, 231-236, 260-265, 287
src/rb_spider/output/human.py                                      479    406    15%   19, 24, 28-30, 34-37, 41-56, 60-73, 77-87, 91-99, 103-108, 112-118, 122-123, 127-135, 139-143, 147-155, 159-165, 169-180, 184-193, 197-205, 209-219, 223-235, 239-250, 254, 260-265, 269-280, 284-287, 291-306, 310-325, 329-336, 340-342, 346-356, 360-366, 370-374, 378-381, 385-391, 395-397, 401-414, 418-433, 441, 454-456, 460, 464-470, 474-483, 487-488, 492-495, 509-513, 517, 521-522, 526-589, 593-600, 604-609, 613-617, 639-645, 649-655, 660-665, 669, 673-675, 680-686, 690-691
src/rb_spider/providers/__init__.py                                  9      1    89%   28
src/rb_spider/providers/base.py                                     58      5    91%   84, 97-99, 119
src/rb_spider/providers/http.py                                     63     63     0%   5-124
src/rb_spider/providers/secrets.py                                  47     23    51%   34, 43, 52, 61-83
----------------------------------------------------------------------------------------------
TOTAL                                                             9367   4699    50%

15 files skipped due to complete coverage.
FAIL Required test coverage of 90.0% not reached. Total coverage: 49.83%
33 passed, 6 warnings in 10.68s
/Users/bolandau/.local/share/uv/python/cpython-3.14.8-macos-aarch64-none/lib/python3.14/collections/__init__.py:455: ResourceWarning: unclosed database in <sqlite3.Connection object at 0x11341cc70>
  result = tuple_new(cls, iterable)
ResourceWarning: Enable tracemalloc to get the object allocation traceback
```

### Answer to question #3

> Round 2 asks for a fix in src/rb_spider/core/maintenance.py (_pg_tables without schema), which is not in Owns.
> Question: Do you add src/rb_spider/core/maintenance.py to the Owns of SPIDER-003?
> Options:
> 1. Add maintenance.py to Owns, I fix _pg_tables with a PostgreSQL test
> 2. Keep it out, finding #1 goes to a new task
> Recommended: Add maintenance.py to Owns, I fix _pg_tables with a PostgreSQL test

maintenance.py is in owns now; the pg_test check has --no-cov. Do the round-2 items: finding #1 fix with a PostgreSQL test, cleanup of orphan files (no row, older than one day). Test first.
