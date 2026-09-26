from __future__ import annotations

from rich.console import Console
from rich.table import Table

# Data goes to stdout; errors and diagnostics go to stderr, so
# `<cli> status > out.txt` never captures an "Error: ..." line as data.
console = Console()
err_console = Console(stderr=True)


def echo(message: str) -> None:
    console.print(message)


def key_values(title: str, pairs: dict) -> None:
    console.print(f"[bold]{title}[/bold]")
    for key, value in pairs.items():
        console.print(f"  {key}: {value}")


def render_doctor(checks: list[dict]) -> None:
    for check in checks:
        mark = "[green]✓[/green]" if check["ok"] else "[red]✗[/red]"
        detail = f" ({check['detail']})" if check.get("detail") else ""
        console.print(f"{mark} {check['name']}{detail}")


def crawls_table(crawls: list[dict]) -> None:
    if not crawls:
        console.print("Обходов пока нет — `spider crawl <url>`.")
        return
    table = Table(box=None, pad_edge=False)
    for column in ("id", "проект", "старт", "статус", "начат", "страниц"):
        table.add_column(column, justify="right" if column in ("id", "страниц") else "left")
    for c in crawls:
        table.add_row(
            str(c["id"]),
            c["project"],
            c["start_url"],
            c["status"],
            c["started_at"][:16].replace("T", " "),
            str(c["pages"]),
        )
    console.print(table)
