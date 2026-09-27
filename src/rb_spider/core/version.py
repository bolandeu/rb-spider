from __future__ import annotations

import functools
from importlib.metadata import PackageNotFoundError, distribution, metadata
from importlib.metadata import version as pkg_version

from .._distribution import DIST_NAME

_PACKAGE_NAME = __name__.split(".")[0]

# The shell command and the project dir (`.spider/`) are named after the tool, not the
# importable package; the distribution (`uv tool install/upgrade`) is `DIST_NAME` (`_distribution.py`).
CLI_NAME = "spider"
__all__ = ["CLI_NAME", "DEV_VERSION", "DIST_NAME", "cli_name", "installed_version", "package_summary"]

DEV_VERSION = "0.0.0-dev"


@functools.cache
def cli_name() -> str:
    """The command users type: this package's console script (`[project.scripts]`, copier's `cli_name`).

    It may differ from the Python package name (command `sitemap-xml`,
    package `rb_sitemap_xml`), so anything that names the command — error
    actions, `{cli}` in docstrings, `auth status`'s `tool` — uses this, while
    the keychain service, env var prefix and `.<package>/` project dir keep
    the package name. A bare source run (nothing installed) falls back to it.
    The distribution (`DIST_NAME`, standard §10 `rb-<slug>`) is a third,
    separate name: what `uv tool install/upgrade` and dependencies use.
    """
    try:
        entry_points = distribution(DIST_NAME).entry_points
    except PackageNotFoundError:
        return _PACKAGE_NAME
    for entry_point in entry_points:
        if entry_point.group == "console_scripts" and entry_point.value.startswith(f"{_PACKAGE_NAME}."):
            return entry_point.name
    return _PACKAGE_NAME


def package_summary() -> str:
    """The one-line `description` from pyproject.toml, as installed."""
    try:
        return metadata(DIST_NAME)["Summary"] or ""
    except PackageNotFoundError:
        return ""


def installed_version() -> str | None:
    """Version of this package as installed, or None when it isn't installed at all.

    None only happens when the source tree is run without any install (not
    even `uv sync`'s editable one) — callers treat it as "dev build" and skip
    anything that would compare versions.
    """
    try:
        return pkg_version(DIST_NAME)
    except PackageNotFoundError:
        return None
