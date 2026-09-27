#!/usr/bin/env bash
# Everything CI runs, locally: lock, lint, format, types, tests (with the JS-rendering tests).
# The pre-push hook runs it (scripts/install_hooks.sh), so nothing red reaches GitHub even while
# GitHub Actions don't run.
#   --py312  also the tests on the oldest supported Python (3.12), in a throwaway environment
#   --linux  also the tests on Linux (Docker), Python 3.12 and 3.14; `scripts/release.py` runs it.
#            JS rendering is left to the macOS run: a browser in the container costs hundreds of MB a run.
#   --pg     also the tests against PostgreSQL (SPIDER_DB_URL, #41): a throwaway postgres container (Docker).
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
    --py312)
      env312="$(mktemp -d)"
      UV_PROJECT_ENVIRONMENT="$env312" uv run --quiet --python 3.12 --extra render --extra curl --extra near --extra structured --extra sitemaps --extra xpath --extra postgres --extra gsc pytest -q -p no:cacheprovider
      rm -rf "$env312"
      ;;
    --linux)
      # The working tree as git sees it (tracked + new, not ignored) — no macOS .venv inside the container,
      # and no AppleDouble ._* files (COPYFILE_DISABLE): pytest would try to import them.
      # uv's cache and its Pythons live in a Docker volume, so runs after the first are quick.
      for python in 3.12 3.14; do
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
      # data on tmpfs: nothing stays on disk; the container goes away with the run
      name="spider-check-pg-$$"
      docker run -d --rm --name "$name" -e POSTGRES_USER=pg -e POSTGRES_PASSWORD=pg -p 127.0.0.1::5432 \
        --tmpfs /var/lib/postgresql/data postgres:17-alpine >/dev/null
      trap 'docker stop "$name" >/dev/null 2>&1 || true' EXIT
      port="$(docker port "$name" 5432/tcp | head -1 | sed 's/.*://')"
      until docker exec "$name" pg_isready -h 127.0.0.1 -U pg >/dev/null 2>&1; do sleep 0.5; done  # TCP: the init server has none
      echo "--- PostgreSQL"
      SPIDER_TEST_PG="postgresql://pg:pg@127.0.0.1:$port/pg" uv run pytest -q --no-cov -p no:cacheprovider
      ;;
    *)
      echo "check.sh: unknown flag $flag (--py312, --linux, --pg)" >&2
      exit 2
      ;;
  esac
done
