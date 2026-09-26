#!/usr/bin/env python3
"""commit-msg hook: enforce the commit subject format and fresh command docs.

1. Subject must be `type(scope): summary` (types and scopes: AGENTS.md,
   «Коммиты»). Merge, revert and fixup!/squash! subjects pass through.
2. For `feat` and `fix` — commits that change behaviour by definition —
   every command whose options or logic changed must have its docstring
   changed too (scripts/check_command_docstrings.py). `refactor`/`perf`
   declare "behaviour unchanged", so their docstrings may stay as they are.

Installed via scripts/install_hooks.sh.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_command_docstrings import find_stale

TYPES = ("feat", "fix", "perf", "refactor", "test", "docs", "build", "chore")
BEHAVIOUR_TYPES = ("feat", "fix")
SUBJECT = re.compile(rf"^(?P<type>{'|'.join(TYPES)})(?:\([a-z0-9-]+\))?!?: \S.*$")
PASSTHROUGH = re.compile(r"^(?:Merge |Revert |fixup! |squash! )")
MAX_SUBJECT = 72


def main(path: str) -> int:
    lines = [line for line in Path(path).read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
    subject = lines[0] if lines else ""

    if PASSTHROUGH.match(subject):
        return 0
    match = SUBJECT.match(subject)
    if not match:
        print(
            f"commit-msg: subject must be `type(scope): summary`, type one of {', '.join(TYPES)}.\n"
            f"  got: {subject!r}\n  see AGENTS.md, «Коммиты»",
            file=sys.stderr,
        )
        return 1
    if len(subject) > MAX_SUBJECT:
        print(f"commit-msg: subject is {len(subject)} chars, max {MAX_SUBJECT}", file=sys.stderr)
        return 1

    if match["type"] in BEHAVIOUR_TYPES and (stale := find_stale()):
        print(
            f"commit-msg: `{match['type']}` changes behaviour, but these commands' --help text did not change:",
            file=sys.stderr,
        )
        for item in stale:
            print(f"  - {item}", file=sys.stderr)
        print("  update the docstring / help= (AGENTS.md, «Документация команд»)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
