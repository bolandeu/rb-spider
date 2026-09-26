from __future__ import annotations

import httpx
import pytest

from rb_spider.core.errors import AuthRequired, ProviderError
from rb_spider.providers import HttpProvider


class _Provider(HttpProvider):
    name = "demo"
    base_url = "https://api.example.test"
    backoff = 0.0

    def __init__(self, handler) -> None:
        self.calls = 0

        def counting(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            return handler(request)

        self.transport = httpx.MockTransport(counting)

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer t"}


def test_success_passes_auth_headers_and_parses_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer t"
        assert request.headers["User-Agent"].startswith("spider/")
        return httpx.Response(200, json={"items": [1, 2]})

    assert _Provider(handler).get_json("/things", page=1) == {"items": [1, 2]}


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_map_to_auth_required(status: int) -> None:
    provider = _Provider(lambda request: httpx.Response(status))
    with pytest.raises(AuthRequired) as excinfo:
        provider.request("GET", "/me")
    assert excinfo.value.exit_code == 3
    assert provider.calls == 1  # never retried


def test_server_errors_are_retried_then_raised() -> None:
    provider = _Provider(lambda request: httpx.Response(503, text="down"))
    with pytest.raises(ProviderError) as excinfo:
        provider.request("GET", "/things")
    assert provider.calls == provider.retries + 1
    assert excinfo.value.exit_code == 5
    assert excinfo.value.to_dict()["status"] == 503


def test_transient_failure_recovers() -> None:
    responses = iter([httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json={})])
    provider = _Provider(lambda request: next(responses))
    assert provider.request("GET", "/things").status_code == 200
    assert provider.calls == 2


def test_client_errors_are_not_retried() -> None:
    provider = _Provider(lambda request: httpx.Response(404, text="nope"))
    with pytest.raises(ProviderError) as excinfo:
        provider.request("GET", "/missing")
    assert provider.calls == 1
    assert excinfo.value.status == 404


def test_network_errors_become_provider_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    provider = _Provider(handler)
    with pytest.raises(ProviderError) as excinfo:
        provider.request("GET", "/things")
    assert provider.calls == provider.retries + 1
    assert "ConnectError" in excinfo.value.message


def test_non_json_body_is_a_provider_error() -> None:
    provider = _Provider(lambda request: httpx.Response(200, text="<html>"))
    with pytest.raises(ProviderError):
        provider.get_json("/things")
