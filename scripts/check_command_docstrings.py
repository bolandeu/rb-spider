#!/usr/bin/env python3
"""Find command functions whose logic changed in the staged diff while their
docstring did not.

A command's docstring and its options' `help=` are the `--help` text people
and agents both work from (AGENTS.md, «Документация команд»), so they change
in the same commit as the behaviour. "Logic" here is the signature (options,
defaults, `help=`) plus the body; a signature change that already touches
`help=` still needs the docstring reviewed, so it counts too.

Not run directly as a hook: scripts/check_commit_msg.py calls `find_stale()`
and blocks `feat`/`fix` commits, where behaviour changes by definition.
Run by hand to preview: `python3 scripts/check_command_docstrings.py`.
"""

from __future__ import annotations

import ast
import subprocess
import sys


def _staged_command_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [path for path in result.stdout.splitlines() if "/commands/" in path and path.endswith(".py")]


def _read(rev: str, path: str) -> str | None:
    result = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def _functions(source: str) -> dict[str, tuple[str | None, str]]:
    """Map public function name -> (docstring, fingerprint of signature + body without docstring)."""
    functions: dict[str, tuple[str | None, str]] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or node.name.startswith("_"):
            continue
        docstring = ast.get_docstring(node)
        body = node.body[1:] if docstring is not None else node.body
        fingerprint = "\n".join(ast.dump(part) for part in [node.args, *node.decorator_list, *body])
        functions[node.name] = (docstring, fingerprint)
    return functions


def find_stale() -> list[str]:
    stale: list[str] = []
    for path in _staged_command_files():
        staged_source = _read("", path)  # ":path" is the staged (index) blob
        if staged_source is None:
            continue
        try:
            new_funcs = _functions(staged_source)
        except SyntaxError:
            continue
        head_source = _read("HEAD", path)
        old_funcs = _functions(head_source) if head_source is not None else {}

        for name, (doc, fingerprint) in new_funcs.items():
            if doc is None:
                stale.append(f"{path}:{name} — no docstring, --help will be empty")
                continue
            old = old_funcs.get(name)
            if old is not None and fingerprint != old[1] and doc == old[0]:
                stale.append(f"{path}:{name} — options or logic changed, docstring did not")
    return stale


if __name__ == "__main__":
    items = find_stale()
    for item in items:
        print(item)
    sys.exit(1 if items else 0)
