from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import settings
from rb_spider.core.errors import InvalidArguments

from . import polygon

DOCS = Path(__file__).parents[1] / "docs" / "profiles.md"
BEGIN, END = "<!-- keys:begin (generated from the settings schema) -->\n", "<!-- keys:end -->"


def _invoke(*args: str, project: Path | None = None):
    return CliRunner().invoke(app, [*(["--project", str(project)] if project else []), *args])


def _invoke_json(*args: str, project: Path | None = None) -> tuple[int, dict]:
    result = _invoke("--json", *args, project=project)
    return result.exit_code, json.loads(result.stdout)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    assert _invoke("init", "--name", "shop", project=tmp_path).exit_code == 0
    return tmp_path


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- layers ------------------------------------------------------------------------


def test_defaults_come_from_the_model() -> None:
    resolved = settings.resolve(None, environ={})
    assert resolved.settings.crawl.concurrency == 20
    assert set(resolved.sources.values()) == {"default"}


def test_each_layer_overrides_the_previous_and_is_recorded(project: Path) -> None:
    _write(settings.global_config_path(), '[crawl]\nconcurrency = 2\nmax_urls = 10\nrobots = "ignore"\n')
    _write(project / ".spider/profiles/p.toml", 'extends = "fast"\n[crawl]\nmax_urls = 30\n')
    extra = _write(project / "extra.toml", "[crawl]\nmax_urls = 40\n")
    resolved = settings.resolve(
        project,
        project_data={"name": "shop", "crawl": {"max_urls": 20}},
        profile="p",
        config_file=extra,
        environ={"SPIDER_CRAWL__MAX_URLS": "50"},
        flags={"crawl.max_urls": 60},
        assignments=["crawl.max_urls=70"],
    )
    assert resolved.settings.crawl.max_urls == 70
    assert resolved.sources["crawl.max_urls"] == "set"
    assert resolved.sources["crawl.concurrency"] == "profile:fast"  # fast (50) beats global (2)
    assert resolved.settings.crawl.concurrency == 50
    assert resolved.sources["crawl.robots"] == "global"
    assert resolved.sources["crawl.user_agent"] == "default"


def test_set_values_are_toml_literals_or_strings() -> None:
    resolved = settings.resolve(
        None, environ={}, assignments=["crawl.robots=report", "crawl.max_urls=5", "crawl.user_agent=Bot/1.0"]
    )
    assert resolved.settings.crawl.robots == "report"
    assert resolved.settings.crawl.max_urls == 5
    assert resolved.settings.crawl.user_agent == "Bot/1.0"


@pytest.mark.parametrize(
    ("assignment", "fragment"),
    [
        ("crawl.max_url=5", "crawl.max_url: Extra inputs are not permitted (from set)"),
        ("crawl.concurrency=0", "crawl.concurrency"),
        ("nokey", "--set expects key=value"),
    ],
)
def test_bad_values_name_the_key_and_layer(assignment: str, fragment: str) -> None:
    with pytest.raises(InvalidArguments, match=fragment.replace("(", r"\(").replace(")", r"\)")):
        settings.resolve(None, environ={}, assignments=[assignment])


def test_env_layer_ignores_non_settings_variables() -> None:
    layer = settings.env_layer({"SPIDER_DB_PATH": "/x", "SPIDER_PROXY_API_KEY": "s", "SPIDER_CRAWL__CONCURRENCY": "3"})
    assert layer == {"crawl": {"concurrency": 3}}


def test_profile_inheritance_loop_and_unknown_parent(project: Path) -> None:
    _write(project / ".spider/profiles/a.toml", 'extends = "b"\n')
    _write(project / ".spider/profiles/b.toml", 'extends = "a"\n')
    with pytest.raises(InvalidArguments, match="loops"):
        settings.profile_layers("a", project)
    with pytest.raises(InvalidArguments, match="No profile 'nope'"):
        settings.profile_layers("nope", project)


def test_builtin_presets_are_valid() -> None:
    assert {"default", "googlebot", "yandexbot", "fast"} <= set(settings.builtin_profiles())
    for name in settings.builtin_profiles():
        settings.profile_layers(name, None)


def test_every_setting_is_described() -> None:
    missing = [key for key, field in settings._field_rows() if not field.description]
    assert not missing


def test_profiles_md_reference_matches_schema() -> None:
    """docs/profiles.md's key table is generated; refresh: SPIDER_UPDATE_SNAPSHOTS=1 uv run pytest."""
    import os

    text = DOCS.read_text(encoding="utf-8")
    generated = settings.reference_markdown()
    head, _, rest = text.partition(BEGIN)
    _, _, tail = rest.partition(END)
    if os.environ.get("SPIDER_UPDATE_SNAPSHOTS"):
        DOCS.write_text(f"{head}{BEGIN}{generated}{END}{tail}", encoding="utf-8")
        text = DOCS.read_text(encoding="utf-8")
    assert f"{BEGIN}{generated}{END}" in text, "docs/profiles.md key table is stale"


PROFILES_BEGIN, PROFILES_END = (
    "<!-- profiles:begin (generated from the built-in profiles) -->\n",
    "<!-- profiles:end -->",
)


def test_profiles_md_lists_the_builtin_profiles() -> None:
    """docs/profiles.md's built-in profiles are generated; refresh: SPIDER_UPDATE_SNAPSHOTS=1 uv run pytest."""
    import os

    text = DOCS.read_text(encoding="utf-8")
    generated = settings.profiles_markdown()
    head, _, rest = text.partition(PROFILES_BEGIN)
    _, _, tail = rest.partition(PROFILES_END)
    if os.environ.get("SPIDER_UPDATE_SNAPSHOTS"):
        DOCS.write_text(f"{head}{PROFILES_BEGIN}{generated}{PROFILES_END}{tail}", encoding="utf-8")
        text = DOCS.read_text(encoding="utf-8")
    assert f"{PROFILES_BEGIN}{generated}{PROFILES_END}" in text, "docs/profiles.md built-in profiles are stale"


def test_every_recipe_in_profiles_md_is_valid(tmp_path: Path) -> None:
    """Each TOML block after «## Рецепты» — hand-written or generated — passes `spider config validate`."""
    recipes = DOCS.read_text(encoding="utf-8").partition("## Рецепты")[2]
    blocks = re.findall(r"```toml\n(.*?)```", recipes, re.DOTALL)
    assert len(blocks) >= 7  # proxy + the built-in profiles
    for i, block in enumerate(blocks):
        path = tmp_path / f"recipe{i}.toml"
        path.write_text(block, encoding="utf-8")
        result = CliRunner().invoke(app, ["--json", "config", "validate", str(path)])
        assert result.exit_code == 0, f"{block}\n{result.stdout}"


# --- CLI ---------------------------------------------------------------------------


def test_config_show_reports_sources(project: Path) -> None:
    code, data = _invoke_json("config", "show", "--profile", "googlebot", "--set", "crawl.max_urls=9", project=project)
    assert code == 0
    assert data["settings"]["crawl"]["max_urls"] == 9
    assert data["sources"]["crawl.max_urls"] == "set"
    assert data["sources"]["crawl.user_agent"] == "profile:googlebot"


def test_config_set_writes_settings_and_init_force_keeps_them(project: Path) -> None:
    assert _invoke("config", "set", "crawl.concurrency", "7", project=project).exit_code == 0
    assert _invoke("init", "--force", "--name", "shop2", project=project).exit_code == 0
    data = tomllib.loads((project / ".spider/config.toml").read_text())
    assert data["crawl"]["concurrency"] == 7
    assert data["name"] == "shop2"
    _, shown = _invoke_json("config", "show", project=project)
    assert shown["sources"]["crawl.concurrency"] == "project"


def test_config_set_rejects_bad_type_and_unknown_key(project: Path) -> None:
    code, payload = _invoke_json("config", "set", "crawl.concurrency", "many", project=project)
    assert code == 2
    assert "crawl.concurrency" in payload["error"]["message"]
    code, _ = _invoke_json("config", "set", "crawl.nope", "1", project=project)
    assert code == 2


def test_config_get_list(project: Path) -> None:
    _invoke("config", "set", "crawl.max_urls", "100", project=project)
    code, got = _invoke_json("config", "get", "crawl.max_urls", project=project)
    assert (code, got["value"]) == (0, 100)
    code, got = _invoke_json("config", "get", "crawl.concurrency", project=project)
    assert got["value"] is None  # not set in the project file
    code, listing = _invoke_json("config", "list", project=project)
    assert listing["crawl"] == {"max_urls": 100}


def test_config_validate_and_schema(tmp_path: Path) -> None:
    good = _write(tmp_path / "good.toml", 'extends = "googlebot"\n[crawl]\nmax_urls = 5\n')
    bad = _write(tmp_path / "bad.toml", "[crawl]\nmax_urls = -1\nspeed = 3\n")
    code, data = _invoke_json("config", "validate", str(good))
    assert (code, data["extends"]) == (0, "googlebot")
    code, data = _invoke_json("config", "validate", str(bad))
    assert code == 2
    assert "crawl.max_urls" in data["error"]["message"]
    assert "crawl.speed" in data["error"]["message"]

    schema = json.loads(_invoke("config", "schema").stdout)
    assert "crawl" in schema["properties"]
    assert "extends" in schema["properties"]


def test_profiles_list_show_init(project: Path) -> None:
    code, listing = _invoke_json("profiles", "list", project=project)
    assert {"default", "googlebot", "yandexbot", "fast"} <= {p["name"] for p in listing["profiles"]}

    code, created = _invoke_json("profiles", "init", "shop", "--from", "googlebot", project=project)
    assert code == 0
    template = Path(created["path"]).read_text()
    assert "# concurrency = 20" in template  # every key present, commented, described
    uncommented = re.sub(r"^# (\w+ = )", r"\1", template, flags=re.MULTILINE)
    settings.ProfileFile.model_validate(tomllib.loads(uncommented))  # uncommenting every key gives a valid profile

    code, shown = _invoke_json("profiles", "show", "shop", project=project)
    assert [level["profile"] for level in shown["chain"]] == ["default", "googlebot", "shop"]
    code, _ = _invoke_json("profiles", "init", "shop", project=project)
    assert code == 2  # exists


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


def test_crawl_uses_settings_and_keeps_snapshot(base_url: str) -> None:
    code, crawl = _invoke_json(
        "crawl", f"{base_url}/", "--profile", "fast", "--set", "crawl.user_agent=SpiderTestBot/1.0", "--max-urls", "2"
    )
    assert code == 0
    assert crawl["pages"] == 2
    assert "SpiderTestBot/1.0" in polygon.SEEN_USER_AGENTS

    code, shown = _invoke_json("crawls", "show")
    assert shown["id"] == crawl["crawl_id"]
    snapshot = shown["settings"]["crawl"]
    assert {k: snapshot[k] for k in ("max_urls", "concurrency", "robots", "user_agent")} == {
        "max_urls": 2,
        "concurrency": 50,
        "robots": "respect",
        "user_agent": "SpiderTestBot/1.0",
    }
