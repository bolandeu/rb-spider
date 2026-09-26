from __future__ import annotations

from pathlib import Path

import pytest

from .test_cli import invoke, invoke_json


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch):
    """In-memory stand-in for the OS keychain so auth tests don't touch it."""
    store: dict[tuple[str, str], str] = {}

    def fake_set_password(service: str, username: str, password: str) -> None:
        store[(service, username)] = password

    def fake_get_password(service: str, username: str) -> str | None:
        return store.get((service, username))

    def fake_delete_password(service: str, username: str) -> None:
        store.pop((service, username), None)

    monkeypatch.setattr("rb_spider.credentials.manager.keyring.set_password", fake_set_password)
    monkeypatch.setattr("rb_spider.credentials.manager.keyring.get_password", fake_get_password)
    monkeypatch.setattr("rb_spider.credentials.manager.keyring.delete_password", fake_delete_password)
    return store


def test_auth_login_logout_status_round_trip(fake_keyring) -> None:
    _, payload = invoke_json("auth", "status", "--provider", "demo")
    assert payload["authenticated"] is False

    result = invoke("auth", "login", "--provider", "demo", "--non-interactive")
    assert result.exit_code == 2  # no env var set, non-interactive can't prompt

    result = invoke(
        "auth",
        "login",
        "--provider",
        "demo",
        "--non-interactive",
        env={"SPIDER_DEMO_API_KEY": "secret"},
    )
    assert result.exit_code == 0

    _, payload = invoke_json("auth", "status", "--provider", "demo")
    assert payload["authenticated"] is True

    assert invoke("auth", "logout", "--provider", "demo").exit_code == 0

    _, payload = invoke_json("auth", "status", "--provider", "demo")
    assert payload["authenticated"] is False


def test_env_var_works_when_keyring_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import keyring.errors

    def broken_get_password(service: str, username: str) -> str | None:
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr("rb_spider.credentials.manager.keyring.get_password", broken_get_password)
    _, payload = invoke_json("auth", "status", "--provider", "demo", env={"SPIDER_DEMO_API_KEY": "secret"})
    assert payload["authenticated"] is True


def test_doctor_reports_credential_checks(tmp_path: Path, fake_keyring) -> None:
    _, payload = invoke_json("--project", str(tmp_path), "doctor")
    names = [check["name"] for check in payload["checks"]]
    assert "credential_store" in names
    # credentials are checked only when the settings need one (test_crawl_settings: the proxy password)
    assert not [name for name in names if name.startswith("credential:")]
