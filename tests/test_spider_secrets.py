"""spider's own secrets in `auth status` (proxy, proxy_key, site, database) and the keychain namespace move.

Before 0.2.0 the keychain held `rb_spider:<provider>` while env vars were `SPIDER_*`; now both
are `spider`. Old entries are still read (`shared_namespaces`, read-only), so passwords saved by an older spider keep working.
"""

from __future__ import annotations

import json

import pytest

from rb_spider.credentials import manager as credentials
from rb_spider.providers import secrets

from .test_auth import by_provider
from .test_cli import invoke

SECRET = "old-proxy-password"  # noqa: S105 — a test value, not a real secret


@pytest.fixture
def keychain(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    """In-memory keychain, `(service, user) -> value`, as in test_auth.fake_keyring."""
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(credentials.keyring, "set_password", lambda s, u, p: store.__setitem__((s, u), p))
    monkeypatch.setattr(credentials.keyring, "get_password", lambda s, u: store.get((s, u)))
    monkeypatch.setattr(credentials.keyring, "delete_password", lambda s, u: store.pop((s, u), None))
    return store


def _status(*args: str, env: dict[str, str] | None = None) -> tuple[int, dict]:
    result = invoke("auth", "status", *args, "--json", env=env or {})
    assert SECRET not in result.output, "a credential value leaked into the output"
    return result.exit_code, json.loads(result.stdout)


def test_all_four_are_optional_and_missing_is_healthy(keychain, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPIDER_DB_URL", raising=False)
    code, payload = _status("--check")
    entries = by_provider(payload)
    assert code == 0 and payload["tool"] == "spider"
    assert {name: (e["required"], e["status"]) for name, e in entries.items()} == {
        "database": (False, "missing"),
        "proxy": (False, "missing"),
        "proxy_key": (False, "missing"),
        "site": (False, "missing"),
    }
    assert entries["proxy"]["source_ref"] == (
        "SPIDER_PROXY_API_KEY or keychain service spider:proxy or rb_spider:proxy"
    )


def test_legacy_keychain_entry_is_still_read(keychain) -> None:
    keychain[("rb_spider:proxy", "proxy")] = json.dumps({"api_key": SECRET})
    assert secrets.password("proxy") == SECRET
    code, payload = _status("--check", "--provider", "proxy")
    proxy = by_provider(payload)["proxy"]
    assert (code, proxy["status"], proxy["source"]) == (0, "ok", "keychain")
    assert proxy["source_ref"] == "keychain service rb_spider:proxy"


def test_login_stores_under_spider_and_logout_leaves_the_legacy_entry(keychain) -> None:
    keychain[("rb_spider:site", "site")] = json.dumps({"api_key": SECRET})
    login = invoke("auth", "login", "--provider", "site", "--non-interactive", env={"SPIDER_SITE_API_KEY": "new"})
    assert login.exit_code == 0
    assert json.loads(keychain[("spider:site", "site")]) == {"api_key": "new"}
    assert secrets.password("site") == "new"  # the new entry wins over the legacy one
    assert invoke("auth", "logout", "--provider", "site").exit_code == 0
    assert ("spider:site", "site") not in keychain
    assert ("rb_spider:site", "site") in keychain  # another namespace is only read, never written
    assert secrets.password("site") == SECRET


def test_database_without_db_url_is_ok_with_a_note(keychain, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPIDER_DB_URL", raising=False)
    _, payload = _status("--check", "--provider", "database", env={"SPIDER_DATABASE_API_KEY": SECRET})
    database = by_provider(payload)["database"]
    assert (database["status"], database["source"]) == ("ok", "env")
    assert "SPIDER_DB_URL is not set" in database["message"]


def test_database_unreachable_is_not_a_failure(keychain) -> None:
    # nothing listens on port 1: the optional provider is `unreachable`, exit stays 0
    env = {"SPIDER_DATABASE_API_KEY": SECRET, "SPIDER_DB_URL": "postgresql://pg@127.0.0.1:1/pg"}
    code, payload = _status("--check", "--provider", "database", env=env)
    assert (code, by_provider(payload)["database"]["status"]) == (0, "unreachable")
