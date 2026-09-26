#!/usr/bin/env python3
"""Reject commit messages whose subject is not `type(scope): summary`.

Types and scopes are listed in AGENTS.md ("Коммиты"). Merge, revert and
fixup!/squash! subjects pass through untouched.

Installed as the commit-msg hook via scripts/install_hooks.sh.
"""

from __future__ import annotations

import re
import sys

TYPES = ("feat", "fix", "perf", "refactor", "test", "docs", "build", "chore")
SUBJECT = re.compile(rf"^(?:{'|'.join(TYPES)})(?:\([a-z0-9-]+\))?!?: \S.*$")
PASSTHROUGH = re.compile(r"^(?:Merge |Revert |fixup! |squash! )")
MAX_SUBJECT = 72


def main(path: str) -> int:
    with open(path, encoding="utf-8") as fh:
        lines = [line for line in fh.read().splitlines() if not line.startswith("#")]
    subject = lines[0] if lines else ""

    if PASSTHROUGH.match(subject):
        return 0
    if not SUBJECT.match(subject):
        print(
            f"commit-msg: subject must be `type(scope): summary`, type one of {', '.join(TYPES)}.\n"
            f"  got: {subject!r}\n  see AGENTS.md, section «Коммиты»",
            file=sys.stderr,
        )
        return 1
    if len(subject) > MAX_SUBJECT:
        print(f"commit-msg: subject is {len(subject)} chars, max {MAX_SUBJECT}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
