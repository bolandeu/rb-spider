from __future__ import annotations

from importlib import resources
from pathlib import Path

import typer

from .. import output
from ..core.version import cli_name

app = output.group("Инструкция spider для ИИ-агентов (SKILL.md).")

_PACKAGE_NAME = __name__.split(".")[0]
_SKILL_NAME = cli_name()  # matches `name:` in the bundled SKILL.md

# Where each AI tool looks for personal (user-level) and project-level skills.
_TOOL_TARGETS = {
    "claude-code": {
        "user": Path.home() / ".claude" / "skills" / _SKILL_NAME,
        "project": Path(".claude") / "skills" / _SKILL_NAME,
    },
    "agents": {
        "user": Path.home() / ".agents" / "skills" / _SKILL_NAME,
        "project": Path(".agents") / "skills" / _SKILL_NAME,
    },
}


def _skill_content() -> str:
    return resources.files(f"{_PACKAGE_NAME}.data").joinpath("SKILL.md").read_text()


@app.command("install")
@output.guard
def install(
    ctx: typer.Context,
    tool: str = typer.Option(
        "claude-code",
        "--tool",
        help=f"Для какого ИИ-инструмента: {', '.join(_TOOL_TARGETS)}.",
    ),
    project: bool = typer.Option(False, "--project", help="Установить в текущий проект, а не в каталог пользователя."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Скопировать встроенный SKILL.md в каталог скиллов ИИ-инструмента.

    Примеры:
      spider skill install                  # ~/.claude/skills/spider/
      spider skill install --tool agents --project

    JSON: `{tool, scope, path}`.
    """
    from ..core.errors import InvalidArguments

    if tool not in _TOOL_TARGETS:
        raise InvalidArguments(f"Unknown --tool '{tool}'. Choose one of: {', '.join(_TOOL_TARGETS)}.")

    scope = "project" if project else "user"
    target_dir = _TOOL_TARGETS[tool][scope]
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "SKILL.md"
    target_path.write_text(_skill_content())

    output.emit_success(
        ctx,
        {"tool": tool, "scope": scope, "path": str(target_path.resolve())},
        render_human=lambda d: output.human.echo(f"Installed skill for '{d['tool']}' ({d['scope']}) at {d['path']}"),
    )
