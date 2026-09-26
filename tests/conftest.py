from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from rb_spider.core import settings


@pytest.fixture(scope="session", autouse=True)
def _isolated_session_db(tmp_path_factory) -> Iterator[None]:
    """Module-scoped fixtures (a shared polygon crawl) are set up before the per-test fixture below:
    without this they would write to the user's real crawl database."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SPIDER_DB_PATH", str(tmp_path_factory.mktemp("session-db") / "spider.sqlite"))
        yield


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path_factory, monkeypatch) -> None:
    """Every test gets its own crawl database and global config — never the user's real ones."""
    monkeypatch.setenv("SPIDER_DB_PATH", str(tmp_path_factory.mktemp("db") / "spider.sqlite"))
    global_config = tmp_path_factory.mktemp("config") / "config.toml"
    monkeypatch.setattr(settings, "global_config_path", lambda: global_config)
    for name in list(os.environ):
        if name.startswith("SPIDER_") and "__" in name:  # settings env layer from the developer's shell
            monkeypatch.delenv(name)
