# Page storage of `spider fetch`: an own cache table and zstd files

`spider fetch` keeps what it fetched, so a repeat fetch of a URL within the term (`SPIDER_CACHE_TTL_DAYS`, 90 days)
comes from the storage and does not request the site (the Human's decision of 2026-10-02, marketer `docs/tools.md`,
«Загрузка страниц»). The index is an own table `spider_fetches` (kind `cache`, PostgreSQL schema `cache`), one row
per URL key and fetch mode; the bodies are zstd files in `SPIDER_CACHE_DIR`, named by a random `cache_key`.

Status: accepted.

## Considered options

1. **Rows in `spider_pages`.** Rejected: crawl tables live per crawl (`crawl_id`, cascade delete) and are `data`;
   a fetch has no crawl, has a term and is a `cache` (it can be fetched again).
2. **The stored-HTML file of crawls (`spider-html*.sqlite`).** Rejected: it is a local SQLite per crawl; it does not
   work as a shared index on the production PostgreSQL.
3. **Own table `spider_fetches` + files** — chosen; the Human's decision names this table.

## Consequences

- Bodies are files, not rows: the shared database stays small, and the files sit on the machine that fetched them
  (production sets `SPIDER_CACHE_DIR=/data/cache/spider`). A row without a readable file is a miss.
- Natural key UNIQUE (`url_key`, `rendered`): the rb-keys `norm_url` of the asked URL and the mode (`--render` or
  not). A new fetch replaces the row and deletes the old file; `cache_key` is random per stored fetch, so two runs
  that store one URL at once never write the same file.
- `cache_key` is a UNIQUE index, not a constraint: `storage.insert_or_replace` replaces by the table's one UNIQUE
  constraint.
- Stored: an HTML answer below 500, not 429, not a failed rendering. Not stored: no answer, 5xx, 429, not HTML —
  these are fetched every time.
- A hit makes no request: the HTTP client, the proxy check, the fingerprint and the browser are set up only at the
  first URL the storage does not answer.
- spider cleans up itself, at most once a day, when a run opens the storage: expired rows and files, then the
  oldest over `SPIDER_CACHE_MAX_GB`, then files without a row older than one day (a run stopped between the file
  and its row; a younger file may be a save in progress).
- Production needs `spider db upgrade` (migration 0036) and schema `cache` with USAGE and CREATE for spider's role.
- The library `rb_spider.fetch` has the storage off by default (`store=False`): its callers write no files unless
  they ask.
