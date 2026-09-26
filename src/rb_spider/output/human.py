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


def issues_table(data: dict) -> None:
    if not data["issues"]:
        console.print(f"Обход #{data['crawl_id']}: проблем не найдено.")
        return
    console.print(f"[bold]Обход #{data['crawl_id']}[/bold] — подробности: spider urls --issue <код>")
    table = Table(box=None, pad_edge=False)
    for column in ("приоритет", "тип", "проверка", "URL", "код"):
        table.add_column(column, justify="right" if column == "URL" else "left")
    for issue in data["issues"]:
        table.add_row(issue["priority"], issue["type"], issue["name"], str(issue["urls"]), issue["code"])
    console.print(table)


def issue_urls_table(data: dict) -> None:
    shown, total = len(data["urls"]), data["total"]
    console.print(
        f"[bold]{data['issue']}[/bold] — обход #{data['crawl_id']}: {total} URL"
        + (f", показаны первые {shown}" if shown < total else "")
    )
    table = Table(box=None, pad_edge=False)
    for column in ("код", "URL", "подробности"):
        table.add_column(column)
    for row in data["urls"]:
        table.add_row(str(row["status_code"] or "—"), row["url"], row["detail"] or "")
    console.print(table)
