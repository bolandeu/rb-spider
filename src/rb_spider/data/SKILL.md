---
name: spider
description: Conventions for driving the spider SEO crawler from an agent — install, JSON output, choosing a crawl profile, the order of analysis commands (drill-down), exit codes, credentials, destructive-command gating. Invoke when a task involves crawling or auditing a website with spider.
---

# spider

Everything command-specific is in the CLI itself — run `spider`
with no arguments for version + command list, `spider <command>
--help` for details. This document only covers what `--help` can't tell
you. If you can run the CLI but not read files, `spider --ai`
prints this document.

## Install (if `spider --version` fails)

```bash
```

From the git tag instead:

```bash
uv tool install "rb-spider @ git+https://github.com/bolandeu/rb-spider.git@vX.Y.Z"
```

Replace `vX.Y.Z` with the latest release tag (install from a tag, never a
branch: [the Standard](https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator/src/branch/main/skills/cli-builder/reference/standard.md), Install).

Same command on macOS, Linux and Windows; `uv tool upgrade rb-spider`
updates it. Do not run from source unless asked to develop the CLI.

## Crawl: pick a profile, don't hand-tune flags

A profile is a named set of crawl settings. `spider profiles list --json`
shows the built-in ones with a one-line purpose; pick by the task:

| Task | Profile |
| --- | --- |
| first look at an unknown site | `quick-audit` |
| full audit of the user's own site | `default` (or `fast` — 50 parallel requests, own sites only) |
| how Google / Yandex see it | `googlebot` / `yandexbot` |
| site renders content with JavaScript (empty HTML, SPA) | `js-site` (needs the `render` extra; exit 1 `RENDER_UNAVAILABLE` says how to install) |
| only broken links and resources | `broken-links` |
| big shop (sorting / filter / utm URLs) | `big-shop`, run with `--detach` |
| migration: check a list of old URLs | `migration` with `spider crawl --list urls.txt` |

- One-off change: `--set section.key=value` (any key, repeatable). Before
  a long crawl, `spider config show --profile X --set … --json` prints the
  final settings and which layer each came from.
- Reusable change: `spider profiles init NAME --from <profile>` writes
  `.spider/profiles/NAME.toml` with every key commented and explained; set
  `extends`, keep only what differs, check with `spider config validate`.
  `spider config schema` is the machine-readable key list.
- Be polite to sites that aren't the user's: keep `crawl.concurrency` low
  and/or set `crawl.max_rps`; robots.txt is respected by default.
- Big crawls: `--detach`, then poll `spider status --json` (pages stored,
  queue left, process alive). An interrupted crawl continues without loss:
  `spider crawls resume`.

## Analysis: drill down, never dump everything

1. Run `spider issues --json`: which checks fired and on how many URLs, most
   urgent first. `not_checked` lists checks whose data wasn't collected —
   never report those as passed.
2. Run `spider urls --issue <code> --json`: the URLs of one check (`--limit`;
   `total` tells how many there are).
3. Run `spider url <url> --json`: everything about one page;
   `spider links <url> --in|--out` — who links to it / where it links;
   `spider redirects` — redirect paths and chains.
4. Only then bulk data: `spider export …` (CSV/JSON, streamed; `-o file`)
   or `spider query "SELECT …"` (read-only SQL) for questions no command
   answers. Report findings as counts plus a few examples, not full lists.

After changing thresholds, `spider analyze` recomputes the checks without
crawling again.

## Conventions

- **`--json` on every command.** Parse stdout; never scrape human output.
  stdout is data only, stderr is diagnostics.
- **Project-aware.** Commands find the project by walking up from the
  current directory, or take `--project PATH`. Not initialized →
  `spider init --non-interactive`.
- **`--non-interactive`** on anything that could prompt. It fails with a
  structured error instead of hanging.
- **Credentials** live in the OS keychain or env vars
  (`SPIDER_<PROVIDER>_<FIELD>`), never in arguments or
  config. `auth status --check --json` reports every provider (source,
  status, expiry, quota — never values; exit 3 if a required one isn't
  ok); log in with `auth login`; never ask the user to paste a secret into
  a command line.
- **Destructive commands** are the ones whose `--help` shows `--dry-run`
  and `--yes` (alias `--confirm`): deleting crawls, projects, pruning.
  Always: run with `--dry-run`, show the user, get explicit sign-off, then
  `--yes --non-interactive`. Never chain straight to `--yes` without a
  human having seen the dry-run.
- **Data** lives in the shared PostgreSQL when `SPIDER_DATABASE_URL` is
  set (else a local SQLite file). `DATABASE_UNAVAILABLE` (exit 5) — the
  server is unreachable, nothing was written anywhere; `DATABASE_NOT_MIGRATED`
  → `spider db upgrade` (changes the shared base: ask the user
  first); `db status --json` shows the revision. Tables are `spider_*`
  (`spider query` reads them); other tools and reports read only the
  `spider_v1_*` views.
- **Page storage** of `spider fetch` is a cache: `from_cache` true means no
  request to the site. Files are zstd in `SPIDER_CACHE_DIR` (default: the user
  cache dir); term `SPIDER_CACHE_TTL_DAYS` (90), limit `SPIDER_CACHE_MAX_GB`
  (none). `--fresh` fetches again, `--max-age <days>` sets the age.
- **`doctor --json`** first when something looks off — it reports
  what the CLI needs to run: its version, the project, its config,
  credential readiness, the database and the external programs.
- **`describe --json`** — the whole CLI as one machine-readable OpenCLI
  document (commands, options, exit codes, env vars, data): the bare
  document, no `{"ok": ...}` envelope.

## Errors

Error envelope: `{"ok": false, "error": {"code", "message", "action"}}`.
Read exit code → `error.code` → `error.action` (the concrete next command).

    0  ok
    1  general (UNEXPECTED = a bug: re-run with --verbose, report; ABORTED = user said no)
    2  invalid arguments
    3  auth required          → spider auth login
    4  project not initialized → spider init
    5  provider error (network / external service; already retried) → retry later
    6  CLI too old for this project → uv tool upgrade rb-spider

Only exit 5 is worth an automatic retry.
