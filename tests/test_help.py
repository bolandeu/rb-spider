"""`--help` is the documentation for people and agents alike (AGENTS.md, «Документация команд»).

Two guarantees:
- every command has a docstring and every option/argument a `help=`;
- every command's rendered `--help` matches a committed snapshot, so any change to the text
  shows up in the diff and gets reviewed. Refresh after an intended change:
  `SPIDER_UPDATE_SNAPSHOTS=1 uv run pytest tests/test_help.py`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import typer.main
from typer.testing import CliRunner

from rb_spider.cli import app

SNAPSHOTS = Path(__file__).parent / "snapshots" / "help"
# Fixed width and no colour, so the rendering is the same on every machine and in CI.
HELP_ENV = {"TERMINAL_WIDTH": "100", "COLUMNS": "100", "NO_COLOR": "1", "_TYPER_FORCE_DISABLE_TERMINAL": "1"}
# Options Typer adds by itself; their help text is not ours to write.
BUILTIN_PARAMS = {"help", "install_completion", "show_completion"}


def _commands(command=None, path: tuple[str, ...] = ()):
    command = command or typer.main.get_command(app)
    yield path, command
    for name, sub in sorted((getattr(command, "commands", None) or {}).items()):
        yield from _commands(sub, (*path, name))


COMMANDS = list(_commands())
IDS = [" ".join(path) or "spider" for path, _ in COMMANDS]


@pytest.mark.parametrize(("path", "command"), COMMANDS, ids=IDS)
def test_command_and_params_are_documented(path, command) -> None:
    assert (command.help or "").strip(), f"`spider {' '.join(path)}` has no docstring"
    missing = [p.name for p in command.params if p.name not in BUILTIN_PARAMS and not getattr(p, "help", None)]
    assert not missing, f"`spider {' '.join(path)}`: options without help=: {missing}"


@pytest.mark.parametrize(("path", "command"), COMMANDS, ids=IDS)
def test_help_matches_snapshot(path, command) -> None:
    result = CliRunner().invoke(app, [*path, "--help"], env=HELP_ENV, prog_name="spider")
    assert result.exit_code == 0, result.output
    # The version in the header changes every release; the snapshot is about the text.
    text = re.sub(r"spider \d+\.\d+\.\d+\S*", "spider <version>", result.output)
    snapshot = SNAPSHOTS / f"{'_'.join(path) or 'spider'}.txt"
    if os.environ.get("SPIDER_UPDATE_SNAPSHOTS"):
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(text)
    assert snapshot.exists(), f"no snapshot for `spider {' '.join(path)} --help`; run with SPIDER_UPDATE_SNAPSHOTS=1"
    assert text == snapshot.read_text(), f"`spider {' '.join(path)} --help` changed; review and refresh the snapshot"
