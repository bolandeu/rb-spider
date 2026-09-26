"""Big-crawl machinery (issue #14): a crawl killed with SIGKILL continues without losing or refetching URLs,
and a detached crawl runs on its own."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import storage
from rb_spider.core.crawl import run_crawl

from . import polygon

pytestmark = pytest.mark.skipif(os.name == "nt", reason="SIGKILL / process groups are POSIX")


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


def _wait(predicate, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.2)


def _stored(engine, crawl_id: int) -> set[str]:
    with engine.connect() as conn:
        return {
            url for (url,) in conn.execute(sa.select(storage.pages.c.url).where(storage.pages.c.crawl_id == crawl_id))
        }


def _short(urls: set[str], base_url: str) -> tuple[set[str], set[str]]:
    local = "http://localhost:" + base_url.rsplit(":", 1)[1]
    internal = {u.removeprefix(base_url) for u in urls if u.startswith(base_url)}
    external = {u.replace(local, "LOCAL") for u in urls if not u.startswith(base_url)}
    return internal, external


def test_kill_9_then_resume_loses_nothing(base_url: str) -> None:
    # ~15 requests/s over the polygon: long enough to kill it midway
    process = subprocess.Popen(  # noqa: S603 — fixed argv
        [sys.executable, "-m", "rb_spider", "--json", "crawl", f"{base_url}/", "--set", "crawl.max_rps=15"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with storage.database() as engine:
        _wait(lambda: storage.list_crawls(engine, limit=1) != [])
        crawl_id = storage.list_crawls(engine, limit=1)[0].id
        _wait(lambda: storage.progress(engine, crawl_id).pages >= 20)
        os.kill(process.pid, signal.SIGKILL)
        process.wait()

        before = storage.progress(engine, crawl_id)
        assert 0 < before.pages < len(polygon.REACHABLE)  # killed midway, with work left
        assert before.pending > 0
        status = json.loads(CliRunner().invoke(app, ["--json", "status", str(crawl_id)]).stdout)["crawl"]
        assert (status["status"], status["alive"]) == ("running", False)  # the process is gone

        result = run_crawl(engine, crawl_id)
        assert result.status == "finished"
        internal, external = _short(_stored(engine, crawl_id), base_url)
        assert internal == polygon.REACHABLE
        assert external == polygon.EXTERNAL
        assert storage.progress(engine, crawl_id).pending == 0  # the queue is fully drained


def test_resume_refuses_finished_crawls(base_url: str) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["--json", "crawl", f"{base_url}/", "--max-urls", "2"]).exit_code == 0
    result = runner.invoke(app, ["--json", "crawls", "resume"])
    assert result.exit_code == 2
    assert "already finished" in json.loads(result.stdout)["error"]["message"]


def test_detach_runs_the_crawl_in_the_background(base_url: str) -> None:
    result = CliRunner().invoke(app, ["--json", "crawl", f"{base_url}/", "--max-urls", "5", "--detach"])
    assert result.exit_code == 0, result.output
    started = json.loads(result.stdout)
    assert started["detached"] is True

    def finished() -> bool:
        status = json.loads(CliRunner().invoke(app, ["--json", "status", str(started["crawl_id"])]).stdout)["crawl"]
        return status["status"] == "finished"

    _wait(finished)
    with storage.database() as engine:
        assert storage.progress(engine, started["crawl_id"]).pages == 5
