from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import typer

from .. import output
from ..core import compare as compare_service
from ..core import storage
from ..core.errors import InvalidArguments
from . import options

Status = StrEnum("Status", {name: name for name in compare_service.STATUSES})


class Urls(StrEnum):
    new = "new"
    missing = "missing"


@output.guard
def compare(
    ctx: typer.Context,
    old: int = typer.Argument(..., help="Номер прежнего обхода (`spider crawls list`)."),
    new: int = typer.Argument(..., help="Номер нового обхода."),
    issue: str | None = typer.Option(None, "--issue", help="Список URL одной проверки (код из `spider issues`)."),
    status: Status = typer.Option(
        "new",
        "--status",
        help="С --issue: added — появилась у старого URL; new — у нового URL; removed — ушла у URL, который "
        "остался; missing — URL с проблемой пропал из обхода.",
    ),
    field: str | None = typer.Option(None, "--field", help="URL, у которых поле изменилось (из compare.fields)."),
    urls: Urls | None = typer.Option(
        None, "--urls", help="new — URL, которых не было; missing — URL, которые пропали."
    ),
    limit: int = typer.Option(100, "--limit", min=1, help="Сколько строк показать (всего — в поле total)."),
    mapping: list[str] | None = typer.Option(
        None,
        "--map",
        metavar="РЕГУЛЯРКА=>ЗАМЕНА",
        help="URL Mapping: URL прежнего обхода переписываются в адреса нового, можно повторять; добавляется к "
        "compare.url_mapping.",
    ),
    profile: str | None = options.ProfileOption,
    config_file: Path | None = options.ConfigFileOption,
    assignments: list[str] | None = options.SetOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сравнить два обхода: новые и пропавшие URL, изменения проблем и полей страниц (Change Detection).

    Для контроля после релиза или миграции: обойдите сайт до и после и сравните.
    Без опций — сводка; по каждой проверке четыре группы, как в Compare mode Screaming
    Frog: added (у URL, который был и раньше, проблема появилась), new (новый URL с
    проблемой), removed (у оставшегося URL проблема ушла), missing (URL с проблемой
    пропал). Поля Change Detection — `compare.fields` (из `--profile` / `--set`); обходы
    сравниваются по URL сайта, при `spider analyze` пороги пересчитываются отдельно.

    URL Mapping — если адреса страниц в обходах разные (staging против production,
    переезд на другой домен или HTTPS, новая структура URL): `--map` или
    `compare.url_mapping` переписывают URL прежнего обхода в адреса нового по
    регулярному выражению, и страницы сравниваются между собой, а не считаются
    пропавшими и новыми.

    Примеры:
      spider compare 12 15
      spider compare 12 15 --issue page_title_missing --status added
      spider --json compare 12 15 --field title --limit 1000
      spider compare 12 15 --urls missing
      spider compare 12 15 --map 'https://staging\\.example\\.com=>https://example.com'

    JSON: сводка — `{old, new, urls: {old, new, new_urls, missing_urls}, issues: [{code, name,
    old, new, added, new_urls, removed, missing}], changes: {поле: число URL}}`; список —
    `{old, new, total, rows}`: для `--issue` / `--urls` — `[{url}]`, для `--field` —
    `[{url, old, new}]`. Несколько списков сразу, неизвестное поле или код, `--map` без
    `=>` или с неверной регуляркой — выход 2.
    """
    settings = options.resolve(ctx, profile, config_file, assignments).settings
    rules = [(rule.pattern, rule.replace) for rule in settings.compare.url_mapping] + [_rule(m) for m in mapping or []]
    with storage.database() as engine:
        old = storage.resolve_crawl_id(engine, old)
        new = storage.resolve_crawl_id(engine, new)
        if issue is None and field is None and urls is None:
            data = {"old": old, "new": new, **compare_service.summary(engine, old, new, settings.compare.fields, rules)}
            output.emit_success(ctx, data, render_human=output.human.compare_summary)
            return
        total, rows = compare_service.details(engine, old, new, issue=issue, status=status.value, field=field,
                                              urls=urls.value if urls else None, limit=limit, mapping=rules)  # fmt: skip
    output.emit_success(ctx, {"old": old, "new": new, "total": total, "rows": rows},
                        render_human=output.human.compare_rows)  # fmt: skip


def _rule(text: str) -> tuple[str, str]:
    """`--map 'pattern=>replacement'` as a rule, the pattern checked."""
    import re

    pattern, sep, replace = text.partition("=>")
    if not sep or not pattern:
        raise InvalidArguments(f"--map '{text}': write it as REGEX=>REPLACEMENT.")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise InvalidArguments(f"--map '{text}': not a regular expression ({exc}).") from exc
    return pattern, replace
