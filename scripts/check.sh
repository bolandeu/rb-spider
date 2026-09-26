#!/usr/bin/env bash
# Everything CI runs, locally: lock, lint, format, types, tests (with the JS-rendering tests).
# The pre-push hook runs it (scripts/install_hooks.sh), so nothing red reaches GitHub even while
# GitHub Actions don't run.
#   --py312  also the tests on the oldest supported Python (3.12), in a throwaway environment
#   --linux  also the tests on Linux (Docker), Python 3.12 and 3.14; `scripts/release.py` runs it.
#            JS rendering is left to the macOS run: a browser in the container costs hundreds of MB a run.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

uv lock --check
uv sync --quiet --extra render --extra curl --extra near
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q

for flag in "$@"; do
  case "$flag" in
    --py312)
      env312="$(mktemp -d)"
      UV_PROJECT_ENVIRONMENT="$env312" uv run --quiet --python 3.12 --extra render --extra curl --extra near pytest -q -p no:cacheprovider
      rm -rf "$env312"
      ;;
    --linux)
      # The working tree as git sees it (tracked + new, not ignored) — no macOS .venv inside the container,
      # and no AppleDouble ._* files (COPYFILE_DISABLE): pytest would try to import them.
      # uv's cache and its Pythons live in a Docker volume, so runs after the first are quick.
      for python in 3.12 3.14; do
        echo "--- Linux, Python $python"
        git ls-files -co --exclude-standard | COPYFILE_DISABLE=1 tar --no-mac-metadata -cf - -T - | docker run --rm -i \
          -v spider-check-uv:/root/.cache/uv -e UV_PYTHON="$python" -e UV_LINK_MODE=copy \
          ghcr.io/astral-sh/uv:bookworm-slim \
          sh -c 'mkdir /src && cd /src && tar -xf - && uv sync --quiet --frozen && uv run pytest -q -p no:cacheprovider'
      done
      ;;
    *)
      echo "check.sh: unknown flag $flag (--py312, --linux)" >&2
      exit 2
      ;;
  esac
done
