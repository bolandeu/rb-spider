"""External integrations (HTTP APIs, LLMs, ...) live here, one module per service.

Subclass `HttpProvider` for anything that speaks HTTP — it already maps
auth failures, rate limits, outages and network errors onto the CLI's
error codes and retries what's safe to retry. Keep API calls out of
`commands/` and `core/services.py`; services call a provider, commands
call a service.

Every concrete provider implements `health_check()` — the hook behind
`<cli> auth status --check` (see `base.Provider`).
"""

from __future__ import annotations

from .base import Health, Provider, Quota, all_providers
from .http import HttpProvider

__all__ = ["Health", "HttpProvider", "Provider", "Quota", "all_providers"]
