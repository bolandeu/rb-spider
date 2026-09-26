"""Bench measure: run `spider crawl` against the local stand, sample RSS of the whole process tree.

    uv run --project bench bench/bench_site.py serve --pages 100000 --workers 4   # the stand, in another shell
    uv run python bench/measure.py "$TMPDIR/bench.sqlite" 0                       # 0 — the whole site

Prints one JSON line: pages, crawl_s and url_per_s (the crawl phase, from the crawl's own timestamps),
analyze_s (checks after it), peak_main_mb / peak_tree_mb (with parser workers), db_mb. Keep the
database outside the repo and delete it after. SPIDER_BIN overrides the command (default .venv/bin/spider).
"""

import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

import psutil

db, max_urls, *extra = sys.argv[1:]
for suffix in ("", "-wal", "-shm"):
    with contextlib.suppress(FileNotFoundError):
        os.remove(db + suffix)
env = {**os.environ, "SPIDER_DB_PATH": db}
cmd = [
    *os.environ.get("SPIDER_BIN", ".venv/bin/spider").split(),
    "--quiet",
    "crawl",
    "http://localhost:8765/",
    "--concurrency",
    "50",
    "--ignore-robots",
    "--json",
    *extra,
]
if int(max_urls):
    cmd += ["--max-urls", max_urls]
t0 = time.monotonic()
proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE)  # noqa: S603 — our own command line
root = psutil.Process(proc.pid)
peak_tree = peak_main = 0
while proc.poll() is None:
    try:
        procs = [root, *root.children(recursive=True)]
        rss = [p.memory_info().rss for p in procs]
        peak_main = max(peak_main, rss[0])
        peak_tree = max(peak_tree, sum(rss))
    except psutil.Error:
        pass
    time.sleep(0.2)
wall = time.monotonic() - t0
out = proc.stdout.read().decode()
result = json.loads(out.strip().splitlines()[-1])
con = sqlite3.connect(db)
started, finished = con.execute("select started_at, finished_at from crawls").fetchone()
crawl_s = (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()
pages = result["pages"]
print(
    json.dumps(
        {
            "pages": pages,
            "crawl_s": round(crawl_s, 1),
            "url_per_s": round(pages / crawl_s),
            "wall_s": round(wall, 1),
            "analyze_s": round(wall - crawl_s, 1),
            "peak_main_mb": peak_main // 2**20,
            "peak_tree_mb": peak_tree // 2**20,
            "db_mb": os.path.getsize(db) // 2**20,
        }
    )
)
