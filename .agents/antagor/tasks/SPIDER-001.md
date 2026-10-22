---
id: SPIDER-001
title: 'Template v1.27.1: bring spider onto the CLI Standard'
status: publish
attempts: 0
blocked: true
blocked_reason: merge_conflict
phase: null
tests_hash: null
publish_stage: merge
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
