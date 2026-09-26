from __future__ import annotations

from importlib.metadata import PackageNotFoundError, metadata
from importlib.metadata import version as pkg_version

_PACKAGE_NAME = __name__.split(".")[0]

# The shell command and the project dir (`.spider/`) are named after the tool, not the
# importable package; the distribution (`uv tool install/upgrade`) is `rb-spider`.
CLI_NAME = "spider"
DIST_NAME = "rb-spider"

DEV_VERSION = "0.0.0-dev"


def package_summary() -> str:
    """The one-line `description` from pyproject.toml, as installed."""
    try:
        return metadata(_PACKAGE_NAME)["Summary"] or ""
    except PackageNotFoundError:
        return ""


def installed_version() -> str | None:
    """Version of this package as installed, or None when it isn't installed at all.

    None only happens when the source tree is run without any install (not
    even `uv sync`'s editable one) — callers treat it as "dev build" and skip
    anything that would compare versions.
    """
    try:
        return pkg_version(_PACKAGE_NAME)
    except PackageNotFoundError:
        return None
