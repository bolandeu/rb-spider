from __future__ import annotations

from importlib import resources

import typer

from . import output
from .commands import (
    auth,
    compare,
    crawl,
    crawls,
    custom,
    db,
    doctor,
    duplicates,
    enrich,
    export,
    fetch,
    hreflang,
    init,
    insecure,
    issues,
    lighthouse,
    link_score,
    links,
    pagination,
    profiles,
    projects,
    redirects,
    report,
    serp,
    sitemaps,
    skill,
    source,
    status,
    structured,
)
from .commands import config as config_cmd
from .core.version import CLI_NAME, DEV_VERSION, installed_version, package_summary

_PACKAGE_NAME = __name__.split(".")[0]

# A bare `<cli>` is the discovery entry point for humans and agents alike:
# name + version + description, then every command with the first line of
# its docstring. No `no_args_is_help` (that exits 2) — main_options() below
# prints this and exits 0. Shell completion stays enabled.
app = typer.Typer(
    help=f"{CLI_NAME} {installed_version() or DEV_VERSION} — {package_summary() or 'project-aware automation CLI'}"
)

app.add_typer(config_cmd.app, name="config")
app.add_typer(auth.app, name="auth")
app.add_typer(skill.app, name="skill")
app.add_typer(crawls.app, name="crawls")
app.add_typer(profiles.app, name="profiles")
app.add_typer(projects.app, name="projects")
app.add_typer(db.app, name="db")
app.add_typer(sitemaps.app, name="sitemaps")
app.add_typer(serp.app, name="serp")
app.add_typer(report.app, name="report")
app.command(name="robots-test")(report.robots_test)
app.command(name="link-score")(link_score.link_score)
app.command(name="source")(source.source)
app.command(name="lighthouse")(lighthouse.lighthouse)

app.command(name="init")(init.init)
app.command(name="status")(status.status)
app.command(name="doctor")(doctor.doctor)
app.command(name="crawl")(crawl.crawl)
app.command(name="issues")(issues.issues)
app.command(name="urls")(issues.urls)
app.command(name="analyze")(issues.analyze)
app.command(name="redirects")(redirects.redirects)
app.command(name="hreflang")(hreflang.hreflang)
app.command(name="pagination")(pagination.pagination)
app.command(name="insecure")(insecure.insecure)
app.command(name="duplicates")(duplicates.duplicates)
app.command(name="structured")(structured.structured)
app.command(name="custom")(custom.custom)
app.command(name="compare")(compare.compare)
app.command(name="links")(links.links)
app.command(name="url")(export.url)
app.command(name="overview")(export.overview)
app.command(name="export")(export.export)
app.command(name="query")(export.query)
app.command(name="fetch")(fetch.fetch)
app.command(name="enrichers")(enrich.enrichers)
app.command(name="enrich")(enrich.enrich)


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(installed_version() or DEV_VERSION)
    raise typer.Exit()


def _ai_callback(value: bool) -> None:
    """Print the bundled agent skill doc to stdout.

    For agents that can execute this CLI but cannot read files from disk
    (e.g. a sandboxed shell with no access to a SKILL.md on the filesystem),
    this is the fallback way to get full usage guidance.
    """
    if not value:
        return
    content = resources.files(f"{_PACKAGE_NAME}.data").joinpath("SKILL.md").read_text()
    typer.echo(content)
    raise typer.Exit()


@app.callback(invoke_without_command=True)
def main_options(
    ctx: typer.Context,
    project: str = typer.Option(
        None, "--project", help="Корень проекта (каталог с `.spider/`); по умолчанию ищется вверх от текущего."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Вывод в JSON для агентов и скриптов (одна строка-конверт `{ok, ...}`)."
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Печатать только основной результат, без пояснений."),
    verbose: bool = typer.Option(False, "--verbose", help="Подробная диагностика в stderr."),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", help="Никогда не задавать вопросов: вместо этого завершиться с ошибкой."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Показать, что будет сделано, ничего не меняя."),
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Показать версию и выйти."
    ),
    ai: bool = typer.Option(
        False,
        "--ai",
        callback=_ai_callback,
        is_eager=True,
        help="Напечатать инструкцию для ИИ-агентов (встроенный SKILL.md) и выйти.",
    ),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["project"] = project
    ctx.obj["json"] = json_output
    ctx.obj["quiet"] = quiet
    ctx.obj["verbose"] = verbose
    ctx.obj["non_interactive"] = non_interactive
    ctx.obj["dry_run"] = dry_run
    output.configure_logging(verbose)
    output.help_if_no_command(ctx)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
