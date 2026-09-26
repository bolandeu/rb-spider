#!/usr/bin/env bash
# Everything CI runs, locally: lock, lint, format, types, tests (with the JS-rendering tests).
# The pre-push hook runs it (scripts/install_hooks.sh), so nothing red reaches GitHub even while
# GitHub Actions don't run. `--py312` also runs the tests on the oldest supported Python.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

uv lock --check
uv sync --quiet --extra render
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q

if [[ "${1:-}" == "--py312" ]]; then
  env312="$(mktemp -d)"
  trap 'rm -rf "$env312"' EXIT
  UV_PROJECT_ENVIRONMENT="$env312" uv run --quiet --python 3.12 --extra render pytest -q -p no:cacheprovider
fi
