"""The HTTP provider: one httpx client with retries, timeouts and the User-Agent of this CLI, and the mapping of HTTP
failures to the CLI's errors.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any

import httpx

from ..core.errors import AuthRequired, ProviderError
from ..core.version import DEV_VERSION, cli_name, installed_version
from .base import Provider

log = logging.getLogger(__name__)

# Responses worth retrying: the server said "not now", not "no".
_RETRY_STATUSES = frozenset({429, 502, 503, 504})
PROBE_TIMEOUT = 10.0  # auth status --check budget per provider, as the httpx timeout


class HttpProvider(Provider):
    """Base class for one HTTP API integration.

    Subclass per service: set `name` and `base_url`, override
    `auth_headers()` to inject the credential (read it via
    `credentials.manager`, never from config), then add typed methods that
    call `self.request(...)` / `self.get_json(...)`. What the wire can throw
    at you is handled once, here:

    - 401 / 403                       -> AuthRequired (exit 3)
    - 429 / 502 / 503 / 504, timeouts,
      connection errors               -> retried `retries` times with
                                         exponential backoff, then
                                         ProviderError (exit 5)
    - any other 4xx / 5xx             -> ProviderError with the status
    - non-JSON body from get_json     -> ProviderError

    Like every provider it must implement `health_check()` (see `Provider`).

    `transport` exists for tests (`httpx.MockTransport`); leave it None
    in real code.
    """

    abstract = True
    base_url: str = ""
    timeout: float = 30.0
    retries: int = 2
    backoff: float = 1.0
    transport: httpx.BaseTransport | None = None

    def auth_headers(self) -> dict[str, str]:
        return {}

    @functools.cached_property
    def client(self) -> httpx.Client:
        user_agent = f"{cli_name()}/{installed_version() or DEV_VERSION}"
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"User-Agent": user_agent, **self.auth_headers()},
            transport=self.transport,
        )

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send one request and return a successful (2xx/3xx) response, or raise a CliError."""
        attempt = 0
        while True:
            try:
                response = self.client.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                if attempt < self.retries:
                    self._sleep(attempt, None)
                    attempt += 1
                    continue
                raise ProviderError(
                    self.name,
                    f"{type(exc).__name__} while calling {method} {path}",
                    action="Check the network connection and the provider's status, then retry.",
                ) from exc

            status = response.status_code
            if status in (401, 403):
                raise AuthRequired(self.name)
            if status in _RETRY_STATUSES and attempt < self.retries:
                self._sleep(attempt, response.headers.get("Retry-After"))
                attempt += 1
                continue
            if response.is_error:
                raise ProviderError(
                    self.name,
                    f"HTTP {status} for {method} {path}: {response.text[:200]}",
                    status=status,
                    action="Retry later." if status in _RETRY_STATUSES else None,
                )
            return response

    def probe(self, path: str, method: str = "GET", **kwargs: Any) -> httpx.Response:
        """One attempt, at most `PROBE_TIMEOUT` seconds, no retries — for `health_check()`.

        Same error mapping as `request()` (401/403 -> AuthRequired, else ProviderError).
        """
        retries, self.retries = self.retries, 0
        try:
            return self.request(method, path, timeout=PROBE_TIMEOUT, **kwargs)
        finally:
            self.retries = retries

    def get_json(self, path: str, **params: Any) -> Any:
        response = self.request("GET", path, params=params or None)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(self.name, f"non-JSON response for GET {path}", status=response.status_code) from exc

    def _sleep(self, attempt: int, retry_after: str | None) -> None:
        delay = self.backoff * (2**attempt)
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        log.debug("%s: retrying in %.1fs (attempt %d/%d)", self.name, delay, attempt + 1, self.retries)
        time.sleep(delay)
