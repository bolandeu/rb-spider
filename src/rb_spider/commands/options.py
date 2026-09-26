"""Options shared by every command that resolves crawl settings (`crawl`, `fetch`, `config show`)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer

from ..core import services, settings
from ..core.errors import InvalidArguments

ProfileOption = typer.Option(
    None, "--profile", help="Профиль настроек: встроенный (`spider profiles list`) или из `.spider/profiles/`."
)
ConfigFileOption = typer.Option(None, "--config", help="TOML-файл настроек поверх профиля (формат как у профиля).")
SetOption = typer.Option(
    None, "--set", help="Переопределить любой ключ: `--set crawl.max_urls=500`; можно повторять.", metavar="KEY=VALUE"
)


def resolve(
    ctx: typer.Context,
    profile: str | None,
    config_file: Path | None,
    assignments: list[str] | None,
    flags: dict[str, Any] | None = None,
) -> settings.Resolved:
    """All eight layers for the project this command runs in (if any)."""
    root = services.find_project_root(Path(ctx.obj.get("project") or Path.cwd()))
    return settings.resolve(
        root,
        project_data=services.read_project_data(root) if root else None,
        profile=profile,
        config_file=config_file,
        flags=flags,
        assignments=assignments,
    )


def read_url_source(source: str) -> str:
    """The text of a `--list` URL file, or of stdin for `-`."""
    if source == "-":
        return sys.stdin.read()
    path = Path(source)
    if not path.is_file():
        raise InvalidArguments(f"No such URL list file: {source}")
    return path.read_text(encoding="utf-8-sig")
