"""SQL text spelled the same in SQLite and PostgreSQL — no SQLAlchemy here: the parsing processes import it."""

from __future__ import annotations


def count_if(condition: str) -> str:
    """SQL counting the rows where `condition` holds — `sum(<boolean>)` works in SQLite only (its booleans are 0 / 1),
    and spider adds no aggregates to the shared PostgreSQL."""
    return f"count(CASE WHEN {condition} THEN 1 END)"
