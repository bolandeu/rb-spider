#!/usr/bin/env bash
# Everything CI runs, locally: lock, lint, format, types, tests (with the JS-rendering tests).
# Other environments than the gate's (`gate check`): Linux, PostgreSQL.
#   --linux  also the tests on Linux (Docker), Python 3.14.
#            JS rendering is left to the macOS run: a browser in the container costs hundreds of MB a run.
#   --pg     also the tests against PostgreSQL: scripts/pg_test.sh (a throwaway postgres:16 container, Docker).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

uv lock --check
uv sync --quiet --extra render --extra curl --extra near --extra structured --extra sitemaps --extra xpath --extra postgres --extra gsc
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q

for flag in "$@"; do
  case "$flag" in
    --linux)
      # The working tree as git sees it (tracked + new, not ignored) — no macOS .venv inside the container,
      # and no AppleDouble ._* files (COPYFILE_DISABLE): pytest would try to import them.
      # uv's cache and its Pythons live in a Docker volume, so runs after the first are quick.
      for python in 3.14; do
        echo "--- Linux, Python $python"
        # Extras without render (a browser costs hundreds of MB a run) and without sitemaps / gsc: those are private
        # GitHub repos (git sources by tag) the container has no credentials for — their tests run on macOS, and so
        # does the coverage floor (release.py --check): without that code covered here it would fail.
        git ls-files -co --exclude-standard | sed 's|^|spider/|' \
          | COPYFILE_DISABLE=1 tar --no-mac-metadata -C .. -cf - -T - 2>/dev/null | docker run --rm -i \
          -v spider-check-uv:/root/.cache/uv -e UV_PYTHON="$python" -e UV_LINK_MODE=copy \
          ghcr.io/astral-sh/uv:bookworm-slim \
          sh -c 'mkdir /work && cd /work && tar -xf - 2>/dev/null && cd spider && uv sync --quiet --frozen --extra curl --extra near --extra structured --extra xpath --extra postgres && uv run pytest -q --no-cov -p no:cacheprovider'
      done
      ;;
    --pg)
      echo "--- PostgreSQL"
      scripts/pg_test.sh -q --no-cov -p no:cacheprovider
      ;;
    *)
      echo "check.sh: unknown flag $flag (--linux, --pg)" >&2
      exit 2
      ;;
  esac
done
