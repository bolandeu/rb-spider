from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path_factory, monkeypatch) -> None:
    """Every test gets its own crawl database — never the user's real one."""
    monkeypatch.setenv("SPIDER_DB_PATH", str(tmp_path_factory.mktemp("db") / "spider.sqlite"))
