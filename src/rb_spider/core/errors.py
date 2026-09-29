from __future__ import annotations

from .._distribution import DIST_NAME
from .version import cli_name

# The real command (`spider`, not the package name) for `action` hints;
# `uv tool upgrade` takes the distribution name (`rb-spider`).
_CLI = cli_name()
_DIST = DIST_NAME


class CliError(Exception):
    """Base error for all expected, user-facing CLI failures.

    Every raise carries a stable `code`, a human `message`, an optional
    `action` telling the caller (human or agent) how to recover, and the
    process exit code to use. Only named, expected failure modes get a
    subclass here; anything else that escapes a command is turned into an
    `UNEXPECTED` envelope by `output.guard`, so `--json` callers always get
    JSON back.
    """

    def __init__(self, code: str, message: str, *, action: str | None = None, exit_code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.exit_code = exit_code

    def to_dict(self) -> dict:
        payload: dict = {"code": self.code, "message": self.message}
        if self.action:
            payload["action"] = self.action
        return payload


class ProjectNotInitialized(CliError):
    def __init__(self, path: str) -> None:
        super().__init__(
            "PROJECT_NOT_INITIALIZED",
            f"No project found at or above '{path}'.",
            action=f"Run '{_CLI} init' in the project directory.",
            exit_code=4,
        )


class AuthRequired(CliError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            "AUTH_REQUIRED",
            f"Authentication is required for provider '{provider}'.",
            action=f"Run '{_CLI} auth login --provider {provider}'.",
            exit_code=3,
        )


class CredentialsUnhealthy(CliError):
    def __init__(self, problems: dict[str, str]) -> None:
        listed = ", ".join(f"{provider} ({status})" for provider, status in problems.items())
        super().__init__(
            "CREDENTIALS_UNHEALTHY",
            f"{len(problems)} credential(s) need attention: {listed}.",
            action=f"See each entry's `message`; store a credential with '{_CLI} auth login --provider <name>'.",
            exit_code=3,
        )


class DependencyTooOld(CliError):
    """Another CLI this one calls is missing or older than required (core/deps.py).

    `dist` is its distribution name — what `uv tool` knows it by (`rb-serp`
    for the `serp` command, standard §10). With `install_url` the action is a
    pinned, runnable install; without it, what to install and no fake URL.
    """

    def __init__(
        self,
        name: str,
        installed: str | None,
        required: str | None,
        *,
        install_url: str | None = None,
        dist: str | None = None,
    ) -> None:
        dist = dist or name
        found = "is not installed" if installed is None else f"is {installed}"
        need = f"{name} >= {required}" if required else name
        if install_url:
            repo = install_url.removesuffix(".git")
            tag = f"v{required}" if required else "<latest release tag>"
            action = f"Run 'uv tool install \"{dist} @ git+{repo}.git@{tag}\" --force', then retry."
        elif installed is not None:
            action = f"Run 'uv tool upgrade {dist}', then retry."
        else:
            action = f"Install {need} (distribution {dist}; see its README for the install command), then retry."
        super().__init__(
            "DEPENDENCY_TOO_OLD",
            f"'{name}' {found}; {_CLI} needs {need}.",
            action=action,
            exit_code=1,
        )


class InvalidArguments(CliError):
    def __init__(self, message: str) -> None:
        super().__init__("INVALID_ARGUMENTS", message, exit_code=2)


class CredentialStoreUnavailable(CliError):
    def __init__(self, provider: str, reason: str) -> None:
        super().__init__(
            "CREDENTIAL_STORE_UNAVAILABLE",
            f"Could not access the OS credential store for provider '{provider}': {reason}",
            action="Set the credential via an environment variable instead of 'auth login' (see 'auth login --help').",
            exit_code=1,
        )


class ProviderError(CliError):
    """An external service failed: network, timeout, HTTP 5xx/429, malformed response.

    `status` is the HTTP status when there was one. Raised by
    `providers.HttpProvider` after its retries are exhausted — commands and
    services normally don't construct this themselves.
    """

    def __init__(self, provider: str, message: str, *, status: int | None = None, action: str | None = None) -> None:
        super().__init__(
            "PROVIDER_ERROR",
            f"Provider '{provider}': {message}",
            action=action or "Retry later; if it keeps failing, check the provider's status page.",
            exit_code=5,
        )
        self.provider = provider
        self.status = status

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["provider"] = self.provider
        if self.status is not None:
            payload["status"] = self.status
        return payload


class ProxyUnavailable(CliError):
    """A proxy of `crawl.proxy_urls` doesn't work and `crawl.proxy_fallback = stop`: nothing goes straight to the site."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            "PROXY_UNAVAILABLE",
            f"The proxy doesn't work: {reason}",
            action=(
                "Check that it is paid and online (the provider's panel), the login in crawl.proxy_urls and the "
                f"password ('{_CLI} auth login --provider proxy'). Or go without it: a run without the proxy profile, "
                "or --set crawl.proxy_fallback=direct (the site sees your IP). "
                f"A stopped crawl continues with '{_CLI} crawls resume'."
            ),
            exit_code=5,
        )


class FingerprintMismatch(CliError):
    """crawl.fingerprint contradicts its OS, this machine or the exit IP, and crawl.fingerprint_check = stop."""

    def __init__(self, issues: list[str]) -> None:
        super().__init__(
            "FINGERPRINT_MISMATCH",
            f"The fingerprint doesn't match: {'; '.join(issues)}",
            action=(
                f"Take a fingerprint for this proxy's country and OS ('{_CLI} fingerprints check NAME --profile …' "
                "shows what's off), set the proxy's OS at the provider, or --set crawl.fingerprint_check=warn."
            ),
            exit_code=2,
        )


class CliTooOld(CliError):
    def __init__(self, installed: str, required: str) -> None:
        super().__init__(
            "CLI_TOO_OLD",
            f"This project requires {_CLI} >= {required}, but {installed} is installed.",
            action=f"Run 'uv tool upgrade {_DIST}' (or lower cli.min_version in the project's config.toml).",
            exit_code=6,
        )


class Aborted(CliError):
    def __init__(self, description: str) -> None:
        super().__init__("ABORTED", f"{description}: aborted by user.", exit_code=1)


class RenderUnavailable(CliError):
    """`crawl.render = "always"` without the optional browser: the `render` extra or the browser binary."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            "RENDER_UNAVAILABLE",
            f"JS rendering needs Playwright and a browser: {reason}",
            action=(
                f'Install it: uv tool install --reinstall "{DIST_NAME}[render] @ git+https://github.com/bolandeu/spider.git" '
                "(in a checkout: uv sync --extra render). A browser: any Chromium in Playwright's cache or Google "
                "Chrome is found by itself; another one — --set crawl.render_browser=<path>; or: playwright install "
                "chromium. Or crawl without rendering: --render never."
            ),
            exit_code=1,
        )


class HttpClientUnavailable(CliError):
    """`crawl.http_client = "curl"` without the `curl` extra."""

    def __init__(self) -> None:
        super().__init__(
            "HTTP_CLIENT_UNAVAILABLE",
            "The curl HTTP client needs curl-cffi, which is not installed.",
            action=(
                f'Install it: uv tool install --reinstall "{DIST_NAME}[curl] @ git+https://github.com/bolandeu/spider.git" '
                "(in a checkout: uv sync --extra curl), or keep the default: --set crawl.http_client=impit."
            ),
            exit_code=1,
        )


class NearDuplicatesUnavailable(CliError):
    """`collect.near_duplicates = true` without the `near` extra."""

    def __init__(self) -> None:
        super().__init__(
            "NEAR_DUPLICATES_UNAVAILABLE",
            "Near duplicates need datasketch (MinHash), which is not installed.",
            action=(
                f'Install it: uv tool install --reinstall "{DIST_NAME}[near] @ git+https://github.com/bolandeu/spider.git" '
                "(in a checkout: uv sync --extra near), or turn it off: --set collect.near_duplicates=false."
            ),
            exit_code=1,
        )


class StructuredDataUnavailable(CliError):
    """Microdata / RDFa in `collect.structured_data` without the `structured` extra."""

    def __init__(self) -> None:
        super().__init__(
            "STRUCTURED_DATA_UNAVAILABLE",
            "Microdata and RDFa need extruct, which is not installed (JSON-LD works without it).",
            action=(
                f'Install it: uv tool install --reinstall "{DIST_NAME}[structured] @ git+https://github.com/bolandeu/spider.git" '
                '(in a checkout: uv sync --extra structured), or keep JSON-LD only: --set collect.structured_data=["json-ld"].'
            ),
            exit_code=1,
        )


class SitemapsUnavailable(CliError):
    """`sitemaps.crawl` / `spider sitemaps build` without the `sitemaps` extra."""

    def __init__(self) -> None:
        super().__init__(
            "SITEMAPS_UNAVAILABLE",
            "XML sitemaps need rb-sitemap-xml, which is not installed.",
            action=(
                f'Install spider with the extra: uv tool install --reinstall "{DIST_NAME}[sitemaps] @ '
                'git+https://github.com/bolandeu/spider.git" (in a checkout: uv sync --extra sitemaps), '
                "or turn it off: --set sitemaps.crawl=false."
            ),
            exit_code=1,
        )


class XPathUnavailable(CliError):
    """A `custom.extract` rule of kind xpath without the `xpath` extra."""

    def __init__(self) -> None:
        super().__init__(
            "XPATH_UNAVAILABLE",
            "Custom Extraction by XPath needs lxml, which is not installed.",
            action=(
                f'Install it: uv tool install --reinstall "{DIST_NAME}[xpath] @ git+https://github.com/bolandeu/spider.git" '
                '(in a checkout: uv sync --extra xpath), or use kind = "css".'
            ),
            exit_code=1,
        )


class RemoteDatabaseUnavailable(CliError):
    """`SPIDER_DB_URL` that can't be used: not PostgreSQL, no driver, no password, or the server doesn't answer."""

    def __init__(self, message: str) -> None:
        super().__init__(
            "REMOTE_DATABASE_UNAVAILABLE",
            message,
            action=(
                "SPIDER_DB_URL — postgresql://user@host:5432/db; the password goes to the keychain: spider auth "
                f'login --provider database. The driver: uv tool install --reinstall "{DIST_NAME}[postgres] @ '
                'git+https://github.com/bolandeu/spider.git" (in a checkout: uv sync --extra postgres). '
                "Without SPIDER_DB_URL crawls go to the local SQLite file."
            ),
            exit_code=1,
        )
