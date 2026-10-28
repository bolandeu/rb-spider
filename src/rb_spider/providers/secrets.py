"""spider's own secrets, as `auth status` reports them (tools/docs/standard-release.md §8).

All four are optional: each is needed only with a setting that uses it. A site password has no endpoint to ask
whether it is right — a crawl is what proves it — so its check only confirms the secret is there. The database
password is checked by connecting to `SPIDER_DATABASE_URL` (when it is set). The proxy is checked by using it:
one TCP connection and one request through each address of `crawl.proxy_urls` (the settings `auth status` resolved
— `use_crawl_settings`), and the result is remembered (core/proxy_state.py).

Before 0.2.0 the keychain held `rb_spider:<provider>`; such entries are still read
(`shared_namespaces`, read-only), so passwords saved by an older spider keep working.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from ..core.errors import AuthRequired, CliError, ProviderError
from ..core.settings import CrawlSettings
from .base import Health, Provider

CHECK_TIMEOUT_S = 10  # credentials.health.CHECK_TIMEOUT: the provider's own client timeout guarantees it


class _Secret(Provider):
    """A password spider needs only with a setting that uses it."""

    abstract = True
    required = False
    shared_namespaces = ("rb_spider",)  # the keychain namespace before 0.2.0


_crawl_settings: Callable[[], CrawlSettings] | None = None


def use_crawl_settings(resolve: Callable[[], CrawlSettings]) -> None:
    """The settings the proxy check goes by: `auth status` resolves them (project config, --profile) like `crawl`."""
    global _crawl_settings
    _crawl_settings = resolve


class ProxyPassword(_Secret):
    """`{password}` in `crawl.proxy_urls` (core/crawl.py, PROXY_CREDENTIAL); checked by using the proxy."""

    name = "proxy"

    def health_check(self) -> Health:
        from ..core import proxy, proxy_state

        if _crawl_settings is None:
            raise ProviderError(self.name, "the settings to check the proxy against are not resolved")
        results = asyncio.run(proxy.check_now(_crawl_settings()))
        if not results:
            return Health(message="present; no crawl.proxy_urls to check")
        dead = [f"{proxy_state.display_address(url)} — {problem}" for url, problem in results if problem]
        if len(dead) == len(results):
            return Health(status="invalid", message="; ".join(dead))
        return Health(message=f"{len(results) - len(dead)} of {len(results)} addresses answer"
                      + (f"; dead: {'; '.join(dead)}" if dead else ""))  # fmt: skip


class ProxyKey(_Secret):
    """`{key}` in `crawl.proxy_change_ip_urls` (core/proxy.py, KEY_CREDENTIAL)."""

    name = "proxy_key"

    def health_check(self) -> Health:
        return Health(message="present; only an IP change proves it")


class SitePassword(_Secret):
    """The site's HTTP Basic password with `crawl.auth = basic` (core/crawl.py, SITE_CREDENTIAL)."""

    name = "site"

    def health_check(self) -> Health:
        return Health(message="present; only a crawl of the site proves it")


class DatabasePassword(_Secret):
    """The password of `SPIDER_DATABASE_URL` when the URL has none (core/db.py, DB_CREDENTIAL)."""

    name = "database"

    def health_check(self) -> Health:
        import sqlalchemy as sa  # heavy: only when actually checking
        from sqlalchemy import exc as sa_exc

        from ..core import db

        url = db.database_url()
        if url is None:
            return Health(message=f"{db.ENV_VAR} is not set: the password isn't used")
        try:
            engine = sa.create_engine(db.postgres_url(url), connect_args={"connect_timeout": CHECK_TIMEOUT_S})
        except (CliError, ModuleNotFoundError) as exc:  # not PostgreSQL, or no psycopg driver
            raise ProviderError(self.name, getattr(exc, "message", str(exc))) from exc
        try:
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
        except sa_exc.OperationalError as exc:
            reason = str(exc.orig).strip()
            if "password authentication failed" in reason:
                raise AuthRequired(self.name) from exc
            raise ProviderError(self.name, f"can't reach the database: {reason}") from exc
        finally:
            engine.dispose()
        return Health()


def password(name: str) -> str | None:
    """The secret of provider `name` (proxy, proxy_key, site, database): env, keychain `spider:`, then legacy
    `rb_spider:`."""
    provider = {cls.name: cls for cls in (ProxyPassword, ProxyKey, SitePassword, DatabasePassword)}[name]
    credential = provider().credential()
    return credential.get("api_key") if credential else None
