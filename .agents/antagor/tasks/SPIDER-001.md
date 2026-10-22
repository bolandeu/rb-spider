---
id: SPIDER-001
title: 'Template v1.27.1: bring spider onto the CLI Standard'
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
- .agents
- .claude
- .copier-answers.yml
- .gitea
- .githooks
- .github
- .gitignore
- .gitleaks.toml
- AGENTS.md
- CHANGELOG.md
- CODING_STANDARDS.md
- CONTEXT.md
- README.md
- changelog.d
- docs
- pyproject.toml
- scripts
- src
- tests
- uv.lock
test_paths: []
docs: none
tools: []
worker_args: null
decision: false
visual: null
depends_on: []
budget_usd: null
epic: null
spec_refs: []
checks: manual
resident: null
tool: null
pr: null
---

Apply the finished migration patch and commit it. The Architect did the work by hand (copier update to cli-generator v1.27.1, conflicts resolved, old release tooling removed, deps on the Gitea registry, requires-python >=3.14) but cannot commit: the pre-commit hook needs a task. Patch: .agents/antagor/scratch/standard-migration.patch (git diff --cached HEAD --binary on HEAD 176c7a9). Steps: git apply --index the patch; run the gate 'uvx --from git+https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator.git@v1.27.1#subdirectory=gate rb-release check' via scripts/run_detached.sh; fix every red step test-first, no lowered floors; commit. Changed existing tests to report: tests/test_cli.py doctor test (project check outside a project is ok now); tests/test_db.py keeps spider's own; template init-help test not taken (spider keeps .spider/).

## Out of scope

- Any behaviour change of spider commands; the release (antagor publish is the Human's)

## Feedback

### Redo from the current main (merge_conflict)

Main now holds the Antagor config (31cc7ce) and the 3 state commits. Redo from main: apply .agents/antagor/scratch/standard-migration.patch if useful (it was made on 176c7a9; the previous result is kept in branch backup/SPIDER-001-manual: cherry-pick its commit 0fdcaee instead, it already passed rb-release check). Run the gate again before submit.

### Blocked: gate_failed (stage gate)

Remote gate (Gitea CI run 420, job 608; log saved by the Architect) failed on the runner: 15 failed + 23 errors, all from the Linux container, not from the migration. (1) No browser: RenderUnavailable 'no browser could start (playwright chromium …)' in tests/test_javascript.py, test_render.py, test_fetch.py::test_render_gives_the_js_page, test_fingerprint.py (3), test_proxy.py::test_the_browser_goes_through_the_proxy_too. Fix in .gitea/workflows/ci.yml: add a step BEFORE the Gate step that installs Chromium for Playwright with system deps (e.g. 'uvx playwright install --with-deps chromium', browsers cached under /cache via PLAYWRIGHT_BROWSERS_PATH) — keep the Gate step LAST (tests/test_ci.py checks it). (2) Other failures to investigate and fix test-first, maybe also browser-related: tests/test_lighthouse.py::test_every_rule_finds_its_page[all] (AssertionError mobile_content_not_sized), tests/test_proxy.py::test_the_browser_refuses_a_socks_proxy_with_a_password (regex did not match). Reproduce on Linux with scripts/check.sh --linux if possible. Do not skip or weaken tests; do not lower floors. If a test truly cannot run on the CI runner, tell the Architect instead of marking it skipped.

### Blocked: gate_failed (stage gate)

Remote gate round 2 (Gitea CI run 421, job 609; log: /private/tmp/claude-501/-Users-bolandau-Work-tools-spider/8c08234b-656f-40e5-b387-3fb85e3a1957/scratchpad/ci421.log). Chromium now installs (uvx playwright@1.63.0 install --with-deps chromium, ok), but it dies at launch: 'BrowserType.launch_persistent_context: Target page, context or browser has been closed' for chromium_headless_shell-1243 and chromium-1243 under /cache/playwright. Same 36 tests as before (test_javascript x30, test_render, test_fetch::test_render_gives_the_js_page, test_fingerprint x3, test_proxy::test_the_browser_goes_through_the_proxy_too) plus test_proxy::test_the_browser_refuses_a_socks_proxy_with_a_password; test_lighthouse now passes. The real browser stderr is cut from the message. Reproduce locally in Docker like the runner: image node:22-bookworm, options --init, run the install step then the pytest of those files as root (see scripts/check.sh --linux for the docker pattern). Likely causes to try, most probable first: (1) /dev/shm is 64 MB in the container -> Chrome crashes: add 'options: --init --shm-size=1g' (or --ipc=host) to container in .gitea/workflows/ci.yml, or '--disable-dev-shm-usage' in the launch args of core/render.py only if the env var/CI needs it; (2) running as root needs --no-sandbox; (3) missing system libs. Print Chromium's real stderr to see which. Prefer the workflow fix over product code. Keep tests/test_ci.py consistent, the Gate step last. No skips, no weaker tests.
