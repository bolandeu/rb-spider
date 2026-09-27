#!/usr/bin/env python3
"""commit-msg hook: enforce the commit subject format.

Subject must be `type(scope): summary` (types and scopes: AGENTS.md,
«Коммиты»). Merge, revert, fixup!/squash! and `Release vX.Y.Z`
(scripts/release.py) subjects pass through.

Fresh command docs are checked by the pre-commit hook
(scripts/check_command_docstrings.py), for every commit type.

Active via `.githooks/commit-msg` (scripts/install_hooks.sh).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TYPES = ("feat", "fix", "perf", "refactor", "test", "docs", "build", "chore")
SUBJECT = re.compile(rf"^(?P<type>{'|'.join(TYPES)})(?:\([a-z0-9-]+\))?!?: \S.*$")
PASSTHROUGH = re.compile(r"^(?:Merge |Revert |fixup! |squash! |Release v\d+\.\d+\.\d+$)")
MAX_SUBJECT = 72


def main(path: str) -> int:
    lines = [line for line in Path(path).read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
    subject = lines[0] if lines else ""

    if PASSTHROUGH.match(subject):
        return 0
    if not SUBJECT.match(subject):
        print(
            f"commit-msg: subject must be `type(scope): summary`, type one of {', '.join(TYPES)}.\n"
            f"  got: {subject!r}\n  see AGENTS.md, «Коммиты»",
            file=sys.stderr,
        )
        return 1
    if len(subject) > MAX_SUBJECT:
        print(f"commit-msg: subject is {len(subject)} chars, max {MAX_SUBJECT}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
