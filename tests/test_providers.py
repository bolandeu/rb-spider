from __future__ import annotations

import gc

import httpx
import pytest

from rb_spider.core.errors import AuthRequired, ProviderError
from rb_spider.providers import Health, HttpProvider, Provider, all_providers
from rb_spider.providers.http import PROBE_TIMEOUT


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


# --- provider contract: every provider can prove its credential works -------------


@pytest.mark.parametrize("provider_cls", all_providers(), ids=lambda cls: cls.name)
def test_every_provider_implements_health_check(provider_cls: type[Provider]) -> None:
    # Only the override is checked: constructing a provider may need config or
    # env, which is `for_health_check()`'s job, not this test's.
    assert provider_cls.health_check is not Provider.health_check, (
        f"{provider_cls.__name__} must implement health_check() — `auth status --check` calls it"
    )


def test_provider_names_are_unique() -> None:
    names = [cls.name for cls in all_providers()]
    assert len(names) == len(set(names)), f"duplicate provider names: {names}"


def test_all_providers_discovers_package_classes_only() -> None:
    # Subclasses stay registered on Provider while they're referenced, so this
    # test drops them (and collects) at the end — later tests see the real set.
    def make_classes() -> tuple[type, type, type]:
        class Found(HttpProvider):
            __module__ = "rb_spider.providers.fake"
            name = "found"

            def health_check(self) -> Health:
                return Health()

        class Base(HttpProvider):
            __module__ = "rb_spider.providers.fake"
            abstract = True

        class Elsewhere(HttpProvider):  # defined outside providers/: not discovered
            name = "elsewhere"

        return Found, Base, Elsewhere

    before = set(all_providers())
    found, base, elsewhere = make_classes()
    discovered = all_providers()
    assert found in discovered
    assert base not in discovered
    assert elsewhere not in discovered
    del found, base, elsewhere, discovered
    gc.collect()
    assert set(all_providers()) == before


def test_probe_is_one_attempt_with_the_check_timeout() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(503)

    provider = _Provider(handler)
    with pytest.raises(ProviderError):
        provider.probe("/me")
    assert len(seen) == 1  # no retries, even for a retryable status
    assert seen[0].extensions["timeout"]["read"] == PROBE_TIMEOUT
    assert provider.retries == 2  # restored afterwards


def test_probe_timeout_is_a_provider_error() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderError) as excinfo:
        _Provider(handler).probe("/me")
    assert calls == [1]
    assert "ReadTimeout" in excinfo.value.message
