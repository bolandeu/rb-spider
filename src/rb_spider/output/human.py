from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.table import Table

# Data goes to stdout; errors and diagnostics go to stderr, so
# `<cli> status > out.txt` never captures an "Error: ..." line as data.
console = Console()
err_console = Console(stderr=True)


def echo(message: str) -> None:
    """Print plain text. Escaped: rich would otherwise treat `[...]` in data as markup and drop it."""
    console.print(escape(message))


def echo_markup(message: str) -> None:
    """Print rich markup (`[green]✓[/green]`); escape() any data you put inside it."""
    console.print(message)


def key_values(title: str, pairs: dict) -> None:
    console.print(f"[bold]{escape(title)}[/bold]")
    for key, value in pairs.items():
        console.print(f"  {escape(str(key))}: {escape(str(value))}")


def render_doctor(checks: list[dict]) -> None:
    for check in checks:
        mark = "[green]✓[/green]" if check["ok"] else "[red]✗[/red]"
        detail = f" ({check['detail']})" if check.get("detail") else ""
        console.print(f"{mark} {escape(check['name'] + detail)}")


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


def fingerprints_table(data: dict) -> None:
    console.print(f"Папка: {data['folder']}")
    table = Table(box=None, pad_edge=False)
    for column in ("отпечаток", "user-agent", "ip"):
        table.add_column(column)
    for f in data["fingerprints"]:
        table.add_row(f["name"], escape(f.get("user_agent") or f.get("error") or ""), f.get("ip") or "")
    console.print(table)


def fingerprint_view(data: dict) -> None:
    key_values(f"Отпечаток: {data['path']}", {**data["headers"], **data["browser"]})
    console.print(f"не подделываются: {', '.join(data['not_faked'])}")


def fingerprint_check(data: dict) -> None:
    where = data["exit_ip"]
    if where:
        console.print(f"Выходной IP: {where['ip']} ({where['country']}, {where['timezone']})")
    else:
        console.print("Выходной IP: не удалось узнать")
    if data["ok"]:
        console.print("[green]Отпечаток согласован.[/green]")
    for issue in data["issues"]:
        console.print(f"[yellow]•[/yellow] {escape(issue)}")


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


def hreflang_list(data: dict) -> None:
    shown, total = len(data["annotations"]), data["total"]
    head = f"[bold]Hreflang ({data['only']})[/bold] — обход #{data['crawl_id']}: {total}"
    console.print(head + (f", показаны первые {shown}" if shown < total else ""))
    table = Table(box=None, pad_edge=False)
    for column in ("страница", "код", "цель", "ответ цели", "обратно"):
        table.add_column(column)
    back = {True: "да", False: "нет", None: "—"}
    for row in data["annotations"]:
        status = row["target_blocked"] or row["target_status"]
        table.add_row(row["source"], row["hreflang"] or "—", row["target"] or "—",
                      "—" if status is None else str(status), back[row["return_link"]])  # fmt: skip
    console.print(table)


def pagination_list(data: dict) -> None:
    shown, total = len(data["links"]), data["total"]
    head = f"[bold]Pagination ({data['only']})[/bold] — обход #{data['crawl_id']}: {total}"
    console.print(head + (f", показаны первые {shown}" if shown < total else ""))
    table = Table(box=None, pad_edge=False)
    for column in ("страница", "rel", "цель", "ответ цели"):
        table.add_column(column)
    for row in data["links"]:
        status = row["target_blocked"] or row["target_status"]
        table.add_row(row["source"], row["rel"], row["target"], "—" if status is None else str(status))
    console.print(table)


def insecure_list(data: dict) -> None:
    shown, total = len(data["links"]), data["total"]
    head = f"[bold]Insecure Content[/bold] — обход #{data['crawl_id']}: {total}"
    console.print(head + (f", показаны первые {shown}" if shown < total else ""))
    table = Table(box=None, pad_edge=False)
    for column in ("HTTPS-страница", "тип", "HTTP-адрес"):
        table.add_column(column)
    for row in data["links"]:
        table.add_row(row["source"], row["kind"], row["target"])
    console.print(table)


def duplicates_list(data: dict) -> None:
    shown, total = len(data["pairs"]), data["total"]
    head = f"[bold]Дубли ({data['kind']})[/bold] — обход #{data['crawl_id']}: {total} пар"
    console.print(head + (f", показаны первые {shown}" if shown < total else ""))
    for pair in data["pairs"]:
        console.print(
            f"{round(100 * pair['similarity'])}% {pair['kind']}: {pair['url']} ≈ {pair['other']}", markup=False
        )
        if pair.get("diff"):
            console.print("\n".join(pair["diff"]), markup=False, highlight=False)
        elif "diff" in pair:
            console.print("  (HTML не сохранялся — нужен обход с --store-html)")


def structured_list(data: dict) -> None:
    console.print(f"[bold]Микроразметка ({data['report']})[/bold] — обход #{data['crawl_id']}")
    table = Table(box=None, pad_edge=False)
    if data["report"] == "features":
        for column in ("функция", "URL", "с ошибками", "с предупреждениями"):
            table.add_column(column)
        for row in data["rows"]:
            table.add_row(row["feature"], str(row["urls"]), str(row["with_errors"]), str(row["with_warnings"]))
    else:
        for column in ("", "где", "сообщение", "URL", "например"):
            table.add_column(column)
        for row in data["rows"]:
            table.add_row(row["severity"], row["scope"], row["message"], str(row["urls"]), row["example"])
    console.print(table)


def sitemaps_rows(data: dict) -> None:
    shown, total = len(data["rows"]), data["total"]
    head = f"[bold]Sitemap ({data['only']})[/bold] — обход #{data['crawl_id']}: {total}"
    console.print(head + (f", показаны первые {shown}" if shown < total else ""))
    if not data["rows"]:
        return
    table = Table(box=None, pad_edge=False)
    columns = list(data["rows"][0])
    for column in columns:
        table.add_column(column)
    for row in data["rows"]:
        table.add_row(*("—" if row[c] is None else str(row[c]) for c in columns))
    console.print(table)


def sitemaps_built(data: dict) -> None:
    console.print(
        f"Обход #{data['crawl_id']}: {data['urls']} URL в {len(data['files'])} файл(ах): {', '.join(data['files'])}"
    )


def serp_view(snippet: dict, heading: str = "Сниппет") -> None:
    console.print(
        f"[bold]{heading}[/bold] (title {snippet['title_px']} px, description {snippet['description_px']} px)"
    )
    console.print(f"  {escape(snippet['url'])}", style="green")
    console.print(f"  {escape(snippet['title'])}", style="bold blue")
    console.print(f"  {escape(snippet['description'])}")


def serp_summary(data: dict) -> None:
    shown, total = len(data["pages"]), data["total"]
    console.print(
        f"[bold]SERP[/bold] — обход #{data['crawl_id']}: {total}"
        + (f", показаны первые {shown}" if shown < total else "")
    )
    table = Table(box=None, pad_edge=False)
    for column in ("URL", "title симв.", "title px", "description симв.", "description px"):
        table.add_column(column)
    for row in data["pages"]:
        cells = [row["title_chars"], row["title_px"], row["description_chars"], row["description_px"]]
        table.add_row(row["url"], *("—" if c is None else str(c) for c in cells))
    console.print(table)


def serp_preview(data: dict) -> None:
    serp_view(data, heading="Предпросмотр сниппета")
    if data["title_truncated"] or data["description_truncated"]:
        cut = [name for name in ("title", "description") if data[f"{name}_truncated"]]
        console.print(f"  обрезано: {', '.join(cut)}")


def custom_view(data: dict) -> None:
    if data.get("rules") is not None:
        table = Table(box=None, pad_edge=False, title=f"Custom — обход #{data['crawl_id']}", title_justify="left")
        for column in ("", "имя", "страниц с совпадением / значением", "без"):
            table.add_column(column)
        for rule in data["rules"]:
            table.add_row(
                rule["kind"], rule["name"], str(rule["pages"]), "—" if rule["without"] is None else str(rule["without"])
            )
        console.print(table)
        return
    shown, total = len(data["rows"]), data["total"]
    head = f"[bold]{data['kind']} «{data['name']}»[/bold] — обход #{data['crawl_id']}: {total}"
    console.print(head + (f", показаны первые {shown}" if shown < total else ""))
    for row in data["rows"]:
        value = row.get("value") if row.get("value") is not None else row.get("n")
        console.print(f"{row['url']}  {'' if value is None else value}", markup=False)


def compare_summary(data: dict) -> None:
    u = data["urls"]
    console.print(f"[bold]Обход #{data['old']} → #{data['new']}[/bold]: URL {u['old']} → {u['new']}, "
                  f"новых {u['new_urls']}, пропало {u['missing_urls']}")  # fmt: skip
    changed = [row for row in data["issues"] if row["added"] or row["new_urls"] or row["removed"] or row["missing"]]
    if changed:
        table = Table(box=None, pad_edge=False, title="Проблемы", title_justify="left")
        for column in ("проверка", "было", "стало", "added", "new", "removed", "missing"):
            table.add_column(column)
        for row in changed:
            table.add_row(
                row["name"], *(str(row[k]) for k in ("old", "new", "added", "new_urls", "removed", "missing"))
            )
        console.print(table)
    moved = {k: v for k, v in data["changes"].items() if v}
    if moved:
        console.print("[bold]Изменились поля[/bold]: " + ", ".join(f"{k} {v}" for k, v in moved.items()))


def compare_rows(data: dict) -> None:
    shown, total = len(data["rows"]), data["total"]
    console.print(
        f"[bold]Обход #{data['old']} → #{data['new']}[/bold]: {total}"
        + (f", показаны первые {shown}" if shown < total else "")
    )
    for row in data["rows"]:
        tail = f"  {row['old']!r} → {row['new']!r}" if "old" in row else ""
        console.print(f"{row['url']}{tail}", markup=False)


def exported_preset(data: dict) -> None:
    console.print(f"Обход #{data['crawl_id']}, пресет {data['preset']} → {data['path']}")
    for name, rows in data["files"].items():
        console.print(f"  {name}: {rows} строк")


def report_rows(data: dict) -> None:
    shown, total = len(data["rows"]), data["total"]
    head = f"[bold]{data['report']}[/bold] — обход #{data['crawl_id']}: {total}"
    console.print(head + (f", показаны первые {shown}" if shown < total else ""))
    if data["rows"]:
        table = Table(box=None, pad_edge=False)
        columns = list(data["rows"][0])
        for column in columns:
            table.add_column(column)
        for row in data["rows"]:
            table.add_row(*("—" if row[c] is None else str(row[c]) for c in columns))
        console.print(table)


def report_structure(data: dict) -> None:
    table = Table(box=None, pad_edge=False, title=f"Структура — обход #{data['crawl_id']}", title_justify="left")
    for column in ("папка", "URL", "индексируется", "нет"):
        table.add_column(column)
    for row in data["folders"]:
        table.add_row(row["folder"], str(row["urls"]), str(row["indexable"]), str(row["non_indexable"]))
    console.print(table)
    console.print("[bold]По глубине[/bold]: " + ", ".join(f"{d}: {n}" for d, n in data["depths"].items()))


def report_response_times(data: dict) -> None:
    console.print(f"[bold]Время ответа[/bold] — обход #{data['crawl_id']}: {data['urls']} URL, "
                  f"среднее {data['average_ms']} мс, максимум {data['max_ms']} мс")  # fmt: skip
    console.print("  " + ", ".join(f"{band} мс: {n}" for band, n in data["bands"].items()))
    for row in data["slowest"]:
        console.print(f"  {row['response_ms']} мс  {row['status_code']}  {row['url']}", markup=False)


def report_path(data: dict) -> None:
    console.print(f"[bold]Путь обхода[/bold] до {data['url']} — обход #{data['crawl_id']}", markup=False)
    for step in data["path"]:
        via = f"  —{step['via']}→" if step["via"] else ""
        console.print(f"  {step['depth']}  {step['url']}{via}", markup=False)


def report_headers(data: dict) -> None:
    title = "Cookies" if data["cookies"] else "Заголовки ответа"
    table = Table(box=None, pad_edge=False, title=f"{title} — обход #{data['crawl_id']}", title_justify="left")
    for column in ("имя", "URL", "например"):
        table.add_column(column)
    for row in data["rows"]:
        table.add_row(row["name"], str(row["urls"]), row["example"])
    console.print(table)


def robots_rows(data: dict) -> None:
    for row in data["rows"]:
        verdict = "[green]разрешён[/green]" if row["allowed"] else "[red]запрещён[/red]"
        console.print(f"{verdict}  {escape(row['url'])}  {escape(row['rule'] or '')}  ({escape(row['user_agent'])})")


def links_table(data: dict) -> None:
    shown, total = len(data["links"]), data["total"]
    arrow = "←" if data["direction"] == "in" else "→"
    head = f"[bold]{data['url']}[/bold] {arrow} обход #{data['crawl_id']}: {total} ссылок"
    console.print(head + (f", показаны первые {shown}" if shown < total else ""))
    table = Table(box=None, pad_edge=False)
    for column in ("код", "URL", "анкор", "тип", "зона"):
        table.add_column(column)
    for link in data["links"]:
        other = link["source"] if data["direction"] == "in" else link["target"]
        kind = link["kind"] + (" nofollow" if link["nofollow"] else "")
        anchor = link["anchor"] or (f"[img alt: {link['alt']}]" if link["alt"] else "")
        status = str(link["status_code"] if link["status_code"] is not None else "—")
        table.add_row(status, other, anchor, kind, link.get("position") or "")
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
            **({"прокси": f"отключён, шли напрямую — {data['proxy_down']}"} if data.get("proxy_down") else {}),
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
        schema += f" (ждут миграции: {', '.join(data['pending_migrations'])} — `spider db upgrade`)"
    key_values(
        "База обходов",
        {"файл" if data.get("engine", "sqlite") == "sqlite" else "PostgreSQL": data["path"],
         "размер": _mb(data["size_bytes"]),
         "свободно внутри": f"{_mb(data['free_bytes'])} (вернёт `spider db vacuum`)",
         "HTML": f"{data['html_path']} ({_mb(data['html_size_bytes'])})" if data["html_path"] else "—",
         "схема": schema, "SQLite": data["sqlite_version"],
         **({"сервер": data["server_version"]} if data.get("server_version") else {}),
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
                       ("blocked", "заблокирован"), ("link_score", "Link Score"), ("screenshot", "скриншот")):  # fmt: skip
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
    if data.get("serp"):
        serp_view(data["serp"], heading="Сниппет в Google")
    if page.get("sd_messages") or page.get("sd_types"):
        console.print(f"[bold]Микроразметка[/bold]: {escape((page.get('sd_types') or '').strip(','))}")
        for severity, scope, *_, text in page.get("sd_messages") or []:
            console.print(f"  {severity} ({scope}) {escape(text)}")
    if data.get("metrics"):
        console.print("[bold]Метрики[/bold]")
        for m in data["metrics"]:
            value = " ".join(str(v) for v in (m["value"], m["text"]) if v is not None)
            console.print(f"  {m['source']}.{m['name']}: {value}")
    if data["resources"]:
        table = Table(box=None, pad_edge=False, title="Ресурсы", title_justify="left")
        for column in ("код", "тип", "КБ", "URL", "alt, размер"):
            table.add_column(column)
        for r in data["resources"]:
            size = f"{r['bytes'] / 1024:.0f}" if r["bytes"] is not None else "—"
            status = str(r["status_code"]) if r["status_code"] is not None else "—"
            dims = f"{r['real_width']}×{r['real_height']}" if r.get("real_width") else ""
            if r.get("display_width") is not None:
                dims += f" → {r['display_width']}×{r['display_height']}"  # as shown on the page
            kind = "фон" if r.get("origin") == "css background" else r["kind"]
            table.add_row(status, kind, size, r["target"], " ".join(filter(None, [r["alt"], dims])))
        console.print(table)
    for strategy, found in (data.get("lighthouse") or {}).items():
        score = found["categories"].get("performance")
        metrics = ", ".join(f"{k} {round(v) if k != 'cls' else round(v, 3)}" for k, v in found["metrics"].items()
                            if v is not None)  # fmt: skip
        source = " — PageSpeed Insights" if found.get("source") == "psi" else ""
        console.print(f"[bold]Lighthouse ({strategy}{source})[/bold]: {round(100 * score) if score is not None else '—'}"
                      f"{' · ' + metrics if metrics else ''}")  # fmt: skip
        for where, label in (("url", "страница"), ("origin", "сайт")):
            crux = (found.get("crux") or {}).get(where)
            if crux:
                shown = ", ".join(f"{name} {m['category'] or '—'}" for name, m in crux.items() if name != "overall")
                console.print(f"  CrUX, {label}: {(crux.get('overall') or {}).get('category') or '—'} · {shown}")
        for audit in found["failed"]:
            console.print(f"  {audit['audit']}: {audit['display'] or audit['score']}")


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
    "directives": "Директивы (HTML 200)", "depth": "Глубина (HTML 200)", "hreflang": "Hreflang (HTML 200)",
    "pagination": "Пагинация", "security": "Протокол (сайт)",
    "structured_data": "Микроразметка", "sitemaps": "Sitemap",
}  # fmt: skip


def overview(data: dict) -> None:
    console.print(
        f"[bold]Обход #{data['crawl_id']}[/bold] — списки: spider export pages --type/--status, spider issues"
    )
    for key, label in _OVERVIEW_LABELS.items():
        values = data.get(key) or {}
        if values:
            console.print(f"[bold]{label}[/bold]: " + ", ".join(f"{k} {v}" for k, v in values.items()))


def link_score(data: dict) -> None:
    console.print(f"[bold]Link Score[/bold] — обход #{data['crawl_id']}: {data['pages']} страниц")
    table = Table(box=None, pad_edge=False)
    for column in ("score", "входящих", "URL"):
        table.add_column(column)
    for row in data["top"]:
        table.add_row(str(row["link_score"]), str(row["inlinks"] or 0), row["url"])
    console.print(table)


def page_source(data: dict) -> None:
    """The HTML or the diff as it is — plain print, so `> page.html` gets a clean file."""
    if "diff" in data:
        print("\n".join(data["diff"]) or "Исходный и отрендеренный HTML совпадают.")
        if data["truncated"]:
            print("… (diff обрезан)")
    else:
        print(data["html"])


def _lh_source(data: dict) -> str:
    return f"{data['strategy']}, PageSpeed Insights" if data.get("source") == "psi" else data["strategy"]


def lighthouse_plan(data: dict) -> None:
    console.print(f"Lighthouse ({_lh_source(data)}) замерит {len(data['urls'])} стр. обхода #{data['crawl_id']}:")
    for url in data["urls"]:
        console.print(f"  {url}")


def lighthouse_progress(page: dict) -> None:
    """One measured page, as it comes (stderr: the result table goes to stdout)."""
    if not page["ok"]:
        err_console.print(f"[red]✗[/red] {page['url']} — {page['error']}")
        return
    score = f"{round(100 * page['performance'])}" if page["performance"] is not None else "—"
    lcp = page["metrics"].get("lcp_ms")
    lcp_text = f", LCP {lcp / 1000:.1f} с" if lcp is not None else ""
    err_console.print(f"[green]✓[/green] {page['url']} — {score}{lcp_text}, не пройдено: {len(page['failed'])}")


def lighthouse_done(data: dict) -> None:
    ok = sum(p["ok"] for p in data["pages"])
    console.print(f"Lighthouse ({_lh_source(data)}), обход #{data['crawl_id']}: замерено {ok} из {len(data['pages'])}"
                  f" стр., находок PageSpeed / Mobile: {data['findings']} — `spider issues`")  # fmt: skip
