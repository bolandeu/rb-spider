from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal

# What a provider's own health check can conclude. `missing` and `unchecked`
# are decided by `auth status` before a check ever runs.
HealthStatus = Literal["ok", "invalid", "expired", "quota_exhausted", "unreachable"]


@dataclass(frozen=True)
class Quota:
    remaining: int | None = None
    limit: int | None = None
    unit: str = "requests"


@dataclass(frozen=True)
class Health:
    """Result of `Provider.health_check()`. Never put a credential value in `message`."""

    status: HealthStatus = "ok"
    expires_at: datetime | None = None
    quota: Quota | None = None
    message: str | None = None


class Provider:
    """Base for every external integration, whatever its transport.

    A concrete provider sets `name` and `credential_fields` (the field names
    it reads via `credentials.manager` under `credential_name`; `()` if it
    needs none), `required`, `per_target` and `legacy_env` where they
    differ, and must implement `health_check()` — `tests/test_providers.py`
    fails for any provider that doesn't. `auth status --check` gets an
    instance via `for_health_check()`: `cls()` by default; a provider whose
    constructor needs arguments overrides it (building them from config/env).

    Classes that are only bases for others set `abstract = True` in their own
    body; everything else defined under `providers/` is discovered by
    `all_providers()`, so there is no registry to forget to update.
    """

    abstract: ClassVar[bool] = True
    name: ClassVar[str] = "default"
    credential_fields: ClassVar[tuple[str, ...]] = ("api_key",)
    # False for a provider the CLI works without: its missing credential is
    # reported but doesn't fail `auth status` (a wrong one still does).
    required: ClassVar[bool] = True
    # True when the credential is per target (a site, host, account): one
    # stored credential per target, named "<name>:<target>" — e.g.
    # `auth login --provider deploy:example.com`. `auth status` reports each
    # stored target separately and sets `target` before `health_check()`.
    per_target: ClassVar[bool] = False
    # Older env var names still honoured, field -> name, checked after
    # <PACKAGE>_<PROVIDER>_<FIELD>. In a subclass keep the annotation (ruff RUF012):
    #     legacy_env: ClassVar[dict[str, str]] = {"api_key": "XMLRIVER_TOKEN"}
    # and read credentials with
    # `manager.get_credential(self.credential_name, env_fields=..., legacy_env=self.legacy_env)`.
    legacy_env: ClassVar[dict[str, str]] = {}
    target: str | None = None

    @classmethod
    def for_health_check(cls, target: str | None = None) -> Provider:
        """An instance for `auth status --check` (for `target`, if per-target)."""
        provider = cls()
        provider.target = target
        return provider

    @property
    def credential_name(self) -> str:
        """The key to read this provider's credential under in `credentials.manager`."""
        return f"{self.name}:{self.target}" if self.per_target and self.target else self.name

    def health_check(self) -> Health:
        """One cheap, read-only, non-billed call proving the credential works.

        Typically `self.get_json("/me")` (or whatever the API's cheapest
        authenticated read is) then `return Health()`; add `expires_at` for
        anything with a lifetime and `quota` if the API reports it. Just let
        `AuthRequired` / `ProviderError` propagate — `auth status` maps them
        to `invalid` / `unreachable`. It must finish within 10 s and not retry:
        `auth status` enforces the 10 s wall clock but can't make a slow check
        fast. `HttpProvider.probe()` makes exactly one such request.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement health_check()")


def all_providers() -> list[type[Provider]]:
    """Every concrete Provider subclass defined in this package, sorted by name."""
    package = __name__.rsplit(".", 1)[0]
    for module in pkgutil.iter_modules(importlib.import_module(package).__path__):
        importlib.import_module(f"{package}.{module.name}")
    found: set[type[Provider]] = set()
    pending = list(Provider.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if cls.__module__.startswith(f"{package}.") and not cls.__dict__.get("abstract", False):
            found.add(cls)
    return sorted(found, key=lambda cls: cls.name)
