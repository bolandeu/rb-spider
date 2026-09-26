from __future__ import annotations

from rich.console import Console
from rich.markup import escape
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
    if data["not_checked"]:
        names = ", ".join(r["name"] for r in data["not_checked"])
        err_console.print(f"Не проверялось (данные не собирались при обходе): {names}")
    if not data["issues"]:
        console.print(f"Обход #{data['crawl_id']}: проблем не найдено.")
        return
    console.print(f"[bold]Обход #{data['crawl_id']}[/bold] — подробности: spider urls --issue <код>")
    table = Table(box=None, pad_edge=False)
    for column in ("приоритет", "тип", "проверка", "URL", "%", "код"):
        table.add_column(column, justify="right" if column in ("URL", "%") else "left")
    for issue in data["issues"]:
        table.add_row(issue["priority"], issue["type"], issue["name"], str(issue["urls"]), f"{issue['percent']:g}",
                      issue["code"])  # fmt: skip
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


def settings_table(data: dict) -> None:
    table = Table(box=None, pad_edge=False)
    for column in ("ключ", "значение", "откуда"):
        table.add_column(column)
    for section, values in data["settings"].items():
        for key, value in values.items():
            dotted = f"{section}.{key}"
            shown = "—" if value is None else str(value).lower() if isinstance(value, bool) else str(value)
            table.add_row(dotted, shown, data["sources"].get(dotted, ""))
    console.print(table)


def profiles_table(data: dict) -> None:
    table = Table(box=None, pad_edge=False)
    for column in ("профиль", "где", "наследует", "описание"):
        table.add_column(column)
    for p in data["profiles"]:
        table.add_row(p["name"], p["where"], p["extends"] or "", escape(p["description"] or ""))
    console.print(table)


def profile_chain(data: dict) -> None:
    for level in data["chain"]:
        console.print(f"[bold]{level['profile']}[/bold]")
        for section, values in level["settings"].items():
            for key, value in values.items():
                console.print(f"  {section}.{key} = {value}")


def crawl_details(data: dict) -> None:
    key_values(
        f"Обход #{data['id']}: {data['status']}",
        {k: data[k] for k in ("project", "start_url", "started_at", "finished_at", "pages")},
    )
    if data["settings"]:
        console.print("[bold]Настройки[/bold]")
        for section, values in data["settings"].items():
            for key, value in values.items():
                console.print(f"  {section}.{key} = {'—' if value is None else value}")


def redirects_list(data: dict) -> None:
    shown, total = len(data["redirects"]), data["total"]
    head = f"[bold]Редиректы ({data['only']})[/bold] — обход #{data['crawl_id']}: {total}"
    console.print(head + (f", показаны первые {shown}" if shown < total else ""))
    for r in data["redirects"]:
        steps = " → ".join(f"{hop['url']} [{hop['status_code'] or '—'} {hop['type']}]" for hop in r["hops"])
        end = "петля" if r["loop"] else f"{r['final_url']} [{r['final_status'] or 'не скачан'}]"
        console.print(f"{steps} → {end}", markup=False)


def links_table(data: dict) -> None:
    shown, total = len(data["links"]), data["total"]
    arrow = "←" if data["direction"] == "in" else "→"
    head = f"[bold]{data['url']}[/bold] {arrow} обход #{data['crawl_id']}: {total} ссылок"
    console.print(head + (f", показаны первые {shown}" if shown < total else ""))
    table = Table(box=None, pad_edge=False)
    for column in ("код", "URL", "анкор", "тип"):
        table.add_column(column)
    for link in data["links"]:
        other = link["source"] if data["direction"] == "in" else link["target"]
        kind = link["kind"] + (" nofollow" if link["nofollow"] else "")
        anchor = link["anchor"] or (f"[img alt: {link['alt']}]" if link["alt"] else "")
        table.add_row(str(link["status_code"] if link["status_code"] is not None else "—"), other, anchor, kind)
    console.print(table)


def status_view(data: dict) -> None:
    if data["project"]:
        key_values("Проект", {"имя": data["project"], "путь": data["path"]})
    crawl = data["crawl"]
    if crawl is None:
        console.print("Обходов пока нет — `spider crawl <url>`.")
        return
    state = crawl["status"]
    if state == "running":
        state += (
            " (процесс жив)"
            if crawl["alive"]
            else " (процесс завершился — `spider crawls resume`)"
            if crawl["alive"] is False
            else ""
        )
    key_values(
        f"Обход #{crawl['id']}: {state}",
        {"проект": crawl["project"], "старт": crawl["start_url"], "сохранено URL": crawl["pages"],
         "в очереди": crawl["pending"], "pid": crawl["pid"] or "—"},
    )  # fmt: skip


def crawl_result(data: dict) -> None:
    key_values(
        f"Обход #{data['crawl_id']}: {data['status']}",
        {
            "проект": data["project"],
            "старт": data["start_url"],
            "страниц": data["pages"],
            "время, с": data["elapsed_s"],
        },
    )


def detached(data: dict) -> None:
    console.print(f"Обход #{data['crawl_id']} запущен в фоне (pid {data['pid']}).")
    console.print(f"  прогресс: spider status {data['crawl_id']}")
    console.print(f"  лог: {data['log']}")


def _mb(size: int) -> str:
    return f"{size / 2**20:.1f} МБ"


def deletion(data: dict) -> None:
    what = ", ".join(f"#{c['id']} {c['project']}" for c in data["crawls"]) or "нечего удалять"
    if data["dry_run"]:
        console.print(f"Будут удалены обходы ({len(data['crawls'])}, {data['pages']} стр.): {what}")
        return
    console.print(f"Удалены обходы ({len(data['crawls'])}, {data['pages']} стр.): {what}")
    if data["crawls"]:
        console.print("  место на диске вернёт `spider db vacuum`")


def projects_table(data: dict) -> None:
    if not data["projects"]:
        console.print("Проектов пока нет — `spider crawl <url>`.")
        return
    table = Table(box=None, pad_edge=False)
    for column in ("проект", "обходов", "страниц", "последний обход"):
        table.add_column(column, justify="right" if column in ("обходов", "страниц") else "left")
    for p in data["projects"]:
        last = p["last_crawl_at"][:16].replace("T", " ") if p["last_crawl_at"] else "—"
        table.add_row(p["name"], str(p["crawls"]), str(p["pages"]), last)
    console.print(table)


def project_deletion(data: dict) -> None:
    verb = "Будет удалён" if data["dry_run"] else "Удалён"
    console.print(f"{verb} проект {data['project']}: обходов {data['crawls']}, страниц {data['pages']}.")


def db_info(data: dict) -> None:
    schema = data["schema_revision"] or "пусто"
    if data["pending_migrations"]:
        schema += f" (ждут миграции: {', '.join(data['pending_migrations'])} — `spider db migrate`)"
    key_values(
        "База обходов",
        {"файл": data["path"], "размер": _mb(data["size_bytes"]),
         "свободно внутри": f"{_mb(data['free_bytes'])} (вернёт `spider db vacuum`)",
         "HTML": f"{data['html_path']} ({_mb(data['html_size_bytes'])})" if data["html_path"] else "—",
         "схема": schema, "SQLite": data["sqlite_version"],
         "проектов / обходов": f"{data['projects']} / {data['crawls']}",
         "страниц / ссылок / находок": f"{data['pages']} / {data['links']} / {data['issues']}"},
    )  # fmt: skip


def migrations(data: dict) -> None:
    if not data["migrations"]:
        console.print(f"Схема актуальна ({data['schema_head']}).")
        return
    verb = "Будут применены" if data["dry_run"] else "Применены"
    console.print(f"{verb} миграции: {', '.join(data['migrations'])}")


def vacuumed(data: dict) -> None:
    console.print(f"Сжато: {_mb(data['before_bytes'])} → {_mb(data['after_bytes'])}")


def exported(data: dict) -> None:
    what = data.get("dataset", "запрос")
    console.print(f"Выгружено {data['rows']} строк ({what}, {data['format']}) в {data['path']}")


def url_details(data: dict) -> None:
    page = data["page"]
    index = "да" if page["indexable"] else f"нет — {page['indexability_status']}"
    fields = {"код": page["status_code"], "тип": page["content_type"] or "—", "индексируется": index,
              "ответ, мс": page.get("response_ms") if page.get("response_ms") is not None else "—",
              "глубина": page["depth"], "размер, байт": page["bytes"],
              "входящих / исходящих ссылок": f"{data['inlinks']} / {data['outlinks']}"}  # fmt: skip
    for key, label in (("redirect_url", "редирект на"), ("refresh_url", "refresh на"), ("canonical_url", "canonical"),
                       ("title", "title"), ("meta_description", "description"), ("h1", "h1"),
                       ("word_count", "слов"), ("last_modified", "Last-Modified"), ("error", "ошибка"),
                       ("blocked", "заблокирован")):  # fmt: skip
        if page.get(key) not in (None, ""):
            fields[label] = page[key]
    key_values(f"{page['url']} — обход #{data['crawl_id']}", fields)
    if data["issues"]:
        console.print("[bold]Проблемы[/bold]")
        for issue in data["issues"]:
            detail = f" — {issue['detail']}" if issue["detail"] else ""
            console.print(f"  {issue['priority'] or ''} {issue['name']} ({issue['code']}){detail}")
    if page.get("headers"):
        console.print("[bold]Заголовки ответа[/bold]")
        for name, value in page["headers"].items():
            console.print(f"  {escape(name)}: {escape(str(value))}")
    if data.get("request_headers"):
        console.print("[bold]Заголовки запроса[/bold]")
        for name, value in data["request_headers"].items():
            console.print(f"  {escape(name)}: {escape(str(value))}")
    if data.get("metrics"):
        console.print("[bold]Метрики[/bold]")
        for m in data["metrics"]:
            value = " ".join(str(v) for v in (m["value"], m["text"]) if v is not None)
            console.print(f"  {m['source']}.{m['name']}: {value}")
    if data["resources"]:
        table = Table(box=None, pad_edge=False, title="Ресурсы", title_justify="left")
        for column in ("код", "тип", "КБ", "URL", "alt"):
            table.add_column(column)
        for r in data["resources"]:
            size = f"{r['bytes'] / 1024:.0f}" if r["bytes"] is not None else "—"
            status = str(r["status_code"]) if r["status_code"] is not None else "—"
            table.add_row(status, r["kind"], size, r["target"], r["alt"] or "")
        console.print(table)


def query_table(data: dict) -> None:
    table = Table(box=None, pad_edge=False)
    for column in data["columns"]:
        table.add_column(column)
    for row in data["rows"]:
        table.add_row(*("—" if v is None else str(v) for v in row))
    console.print(table)
    if data["truncated"]:
        err_console.print(f"Показаны первые {len(data['rows'])} строк — все: --format csv -o <файл>.")


def enrichers_table(data: dict) -> None:
    if not data["enrichers"]:
        console.print("Обогатители не установлены — это пакеты с entry point `rb_spider.enrichers`.")
        return
    for p in data["enrichers"]:
        state = f"[red]не загружается: {p['error']}[/red]" if p["error"] else p["description"]
        console.print(f"[bold]{p['name']}[/bold] ({p['target']}) — {state}")


def enriched(data: dict) -> None:
    if not data["stored"]:
        console.print("Обогатители не установлены — запускать нечего (`spider enrichers`).")
        return
    for name, count in data["stored"].items():
        console.print(f"{name}: сохранено метрик — {count} (обход #{data['crawl_id']})")


def fetched(data: dict) -> None:
    status = data["status"] if data["status"] is not None else "—"
    where = data.get("final_url") or data["url"]
    moved = f" ← {data['url']}" if data.get("redirects") else ""
    title = (data.get("seo") or {}).get("title") or data.get("error") or ""
    console.print(f"{status}  {where}{moved}  {escape(title)}  [dim]{data.get('elapsed_ms')} мс[/dim]")


_OVERVIEW_LABELS = {
    "totals": "Итого", "content_types": "Типы (сайт)", "external_content_types": "Типы (чужие сайты)",
    "status": "Коды ответа", "indexability": "Индексируемость", "canonicals": "Canonical (HTML 200)",
    "directives": "Директивы (HTML 200)", "depth": "Глубина (HTML 200)",
}  # fmt: skip


def overview(data: dict) -> None:
    console.print(
        f"[bold]Обход #{data['crawl_id']}[/bold] — списки: spider export pages --type/--status, spider issues"
    )
    for key, label in _OVERVIEW_LABELS.items():
        values = data.get(key) or {}
        if values:
            console.print(f"[bold]{label}[/bold]: " + ", ".join(f"{k} {v}" for k, v in values.items()))
