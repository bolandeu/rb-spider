"""Crawl settings: one pydantic model, eight layers, and where every value came from.

Layers, each overriding the ones before it (docs/spec.md, section 4):

    default → global → project → profile (with `extends`) → --config file → env → flags → --set

Layers are merged here as flat `section.key` dicts rather than through pydantic-settings, because
`spider config show` must say which layer each value came from — provenance pydantic-settings
doesn't keep. A layer only contributes keys it sets explicitly, so a project file never shadows
the global one with defaults.

Every field has a `description=`: it is the help text of the key in `config show`, the
commented template of `profiles init`, the JSON Schema and docs/profiles.md.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import InvalidArguments
from .version import CLI_NAME

_PACKAGE_NAME = __name__.split(".")[0]


class CrawlSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_urls: int | None = Field(
        None, ge=1, description="Остановиться после стольких URL; не задано — обойти весь сайт.", examples=[50000]
    )
    concurrency: int = Field(20, ge=1, le=500, description="Сколько запросов к сайту выполняется одновременно.")
    respect_robots: bool = Field(
        True, description="Соблюдать robots.txt: запрещённые URL не скачиваются, но попадают в отчёт."
    )
    store_html: bool = Field(
        False, description="Сохранять HTML страниц (сжатым, в отдельный файл рядом с базой); иначе только md5."
    )
    user_agent: str | None = Field(
        None,
        description="Заголовок User-Agent запросов; не задано — как у обычного браузера (Firefox).",
        examples=["Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"],
    )


class ThresholdSettings(BaseModel):
    """Limits the issue rules compare against. Changing them needs `spider analyze`, not a new crawl."""

    model_config = ConfigDict(extra="forbid")

    redirect_chain_hops: int = Field(
        2, ge=2, description="Со скольких прыжков редирект считается цепочкой (Internal Redirect Chain)."
    )
    title_max_chars: int = Field(60, ge=1, description="Title длиннее — «Page Titles: Over … Characters».")
    title_min_chars: int = Field(30, ge=1, description="Title короче — «Page Titles: Below … Characters».")
    description_max_chars: int = Field(
        155, ge=1, description="Meta description длиннее — «Meta Description: Over … Characters»."
    )
    description_min_chars: int = Field(
        70, ge=1, description="Meta description короче — «Meta Description: Below … Characters»."
    )
    h1_max_chars: int = Field(70, ge=1, description="H1 длиннее — «H1: Over … Characters».")
    h2_max_chars: int = Field(70, ge=1, description="H2 длиннее — «H2: Over … Characters».")
    low_content_words: int = Field(
        200, ge=1, description="Меньше слов в видимом тексте — «Content: Low Content Pages»."
    )


class Settings(BaseModel):
    """Everything a crawl can be configured with. Sections are TOML tables: `[crawl]`, `[thresholds]`."""

    model_config = ConfigDict(extra="forbid")

    crawl: CrawlSettings = Field(default_factory=CrawlSettings, description="Как обходить сайт.")
    thresholds: ThresholdSettings = Field(
        default_factory=ThresholdSettings, description="Пороги проверок; пересчёт без обхода — `spider analyze`."
    )


class ProfileFile(Settings):
    """A profile / `--config` file: settings plus its own metadata."""

    description: str | None = Field(None, description="Для чего профиль — видно в `spider profiles list`.")
    extends: str | None = Field(None, description="Профиль, от которого наследуются незаданные ключи.")


SECTIONS = tuple(Settings.model_fields)
_ENV_PREFIX = f"{CLI_NAME.upper()}_"


# --- flat dotted-key dicts --------------------------------------------------------------


def flatten(data: dict, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, f"{dotted}."))
        else:
            flat[dotted] = value
    return flat


def unflatten(flat: dict[str, Any]) -> dict:
    nested: dict = {}
    for dotted, value in flat.items():
        *parents, leaf = dotted.split(".")
        node = nested
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return nested


def settings_keys() -> list[str]:
    """Every settable key, `section.key`."""
    return [
        f"{section}.{key}" for section in SECTIONS for key in Settings.model_fields[section].annotation.model_fields
    ]  # type: ignore[union-attr]


# --- layer sources ----------------------------------------------------------------------


def _read_toml(path: Path, label: str) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise InvalidArguments(f"{label}: not valid TOML ({exc}).") from exc


def _settings_part(data: dict) -> dict:
    return {k: v for k, v in data.items() if k in SECTIONS}


def global_config_path() -> Path:
    return Path(platformdirs.user_config_dir(CLI_NAME, appauthor=False)) / "config.toml"


def builtin_profiles() -> dict[str, Path]:
    folder = resources.files(f"{_PACKAGE_NAME}.data").joinpath("profiles")
    return {Path(p.name).stem: Path(str(p)) for p in folder.iterdir() if p.name.endswith(".toml")}


def project_profiles(project_root: Path | None) -> dict[str, Path]:
    if project_root is None:
        return {}
    folder = project_root / f".{CLI_NAME}" / "profiles"
    return {p.stem: p for p in sorted(folder.glob("*.toml"))} if folder.is_dir() else {}


def available_profiles(project_root: Path | None) -> dict[str, tuple[str, Path]]:
    """name -> (where, path); a project profile shadows a built-in one of the same name."""
    found = {name: ("builtin", path) for name, path in builtin_profiles().items()}
    found.update({name: ("project", path) for name, path in project_profiles(project_root).items()})
    return found


def load_profile_file(path: Path, label: str) -> ProfileFile:
    try:
        return ProfileFile.model_validate(_read_toml(path, label))
    except ValidationError as exc:
        raise InvalidArguments(_explain(exc, label)) from exc


def profile_layers(name: str, project_root: Path | None) -> list[tuple[str, dict]]:
    """The profile and its `extends` ancestors as layers, most general first."""
    profiles = available_profiles(project_root)
    chain: list[tuple[str, dict]] = []
    seen: list[str] = []
    current: str | None = name
    while current is not None:
        if current in seen:
            raise InvalidArguments(f"Profile inheritance loops: {' → '.join([*seen, current])}.")
        if current not in profiles:
            known = ", ".join(sorted(profiles))
            raise InvalidArguments(f"No profile '{current}'. Available: {known} (`spider profiles list`).")
        seen.append(current)
        _, path = profiles[current]
        profile = load_profile_file(path, f"profile '{current}' ({path})")  # validates keys and types
        chain.append((f"profile:{current}", _settings_part(_read_toml(path, str(path)))))
        current = profile.extends
    return list(reversed(chain))


def env_layer(environ: dict[str, str]) -> dict:
    """`SPIDER_CRAWL__MAX_URLS=500` → {"crawl": {"max_urls": "500"}}. Only double-underscore names count,
    so `SPIDER_DB_PATH` and credential variables (`SPIDER_<PROVIDER>_<FIELD>`) are left alone."""
    flat = {}
    for name, value in environ.items():
        if name.startswith(_ENV_PREFIX) and "__" in name:
            section, _, key = name.removeprefix(_ENV_PREFIX).lower().partition("__")
            flat[f"{section}.{key}"] = parse_value(value)
    return unflatten(flat)


def parse_value(raw: str) -> Any:
    """A TOML literal when it is one (`1000`, `true`, `["a"]`, `"x"`), otherwise the plain string."""
    try:
        return tomllib.loads(f"v = {raw}")["v"]
    except tomllib.TOMLDecodeError:
        return raw


def set_layer(assignments: list[str]) -> dict:
    flat = {}
    for item in assignments:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise InvalidArguments(f"--set expects key=value, got '{item}'.")
        flat[key.strip()] = parse_value(value.strip())
    return unflatten(flat)


# --- resolution -------------------------------------------------------------------------


@dataclass
class Resolved:
    settings: Settings
    sources: dict[str, str]  # section.key -> layer label ("default", "project", "profile:fast", "set", ...)


def _explain(exc: ValidationError, where: str, sources: dict[str, str] | None = None) -> str:
    problems = []
    for error in exc.errors():
        key = ".".join(str(part) for part in error["loc"])
        origin = f" (from {sources[key]})" if sources and key in sources else ""
        problems.append(f"{key}: {error['msg']}{origin}")
    return f"{where}: " + "; ".join(problems) + ". Valid keys: `spider config schema`."


def resolve(
    project_root: Path | None,
    *,
    project_data: dict | None = None,
    profile: str | None = None,
    config_file: Path | None = None,
    flags: dict[str, Any] | None = None,
    assignments: list[str] | None = None,
    environ: dict[str, str] | None = None,
) -> Resolved:
    """Merge all layers into validated Settings, remembering the layer each value came from."""
    layers: list[tuple[str, dict]] = []
    global_path = global_config_path()
    if global_path.is_file():
        layers.append(("global", _settings_part(_read_toml(global_path, f"global config ({global_path})"))))
    if project_data:
        layers.append(("project", _settings_part(project_data)))
    if profile:
        layers.extend(profile_layers(profile, project_root))
    if config_file:
        if not config_file.is_file():
            raise InvalidArguments(f"--config: no file '{config_file}'.")
        layers.append((f"file:{config_file}", _settings_part(_read_toml(config_file, f"--config {config_file}"))))
    layers.append(("env", env_layer(dict(os.environ) if environ is None else environ)))
    layers.append(("flag", unflatten({k: v for k, v in (flags or {}).items() if v is not None})))
    layers.append(("set", set_layer(assignments or [])))

    merged: dict[str, Any] = {}
    sources = dict.fromkeys(settings_keys(), "default")
    for label, data in layers:
        for key, value in flatten(data).items():
            merged[key] = value
            sources[key] = label
    try:
        settings = Settings.model_validate(unflatten(merged))
    except ValidationError as exc:
        raise InvalidArguments(_explain(exc, "Invalid settings", sources)) from exc
    return Resolved(settings, sources)


# --- docs -------------------------------------------------------------------------------


def _field_rows() -> list[tuple[str, Any]]:
    rows = []
    for section in SECTIONS:
        model = Settings.model_fields[section].annotation
        for key, field in model.model_fields.items():  # type: ignore[union-attr]
            rows.append((f"{section}.{key}", field))
    return rows


def _toml_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def profile_template(name: str, extends: str | None) -> str:
    """A profile file with every key commented out, described, and set to its default/example."""
    lines = [
        f"# Профиль spider «{name}». Раскомментируйте нужные ключи.",
        "# Справочник ключей — docs/profiles.md; проверить файл — `spider config validate <файл>`.",
        "",
        'description = ""',
        f'extends = "{extends}"' if extends else '# extends = "default"',
    ]
    current = None
    for dotted, field in _field_rows():
        section, key = dotted.split(".", 1)
        if section != current:
            lines += ["", f"[{section}]"]
            current = section
        value = field.default if field.default is not None else (field.examples or [None])[0]
        lines.append(f"# {field.description}")
        lines.append(f"# {key} = {_toml_literal(value)}" if value is not None else f"# {key} =")
    return "\n".join(lines) + "\n"


def reference_markdown() -> str:
    """The key reference table for docs/profiles.md."""
    lines = ["| Ключ | Тип | По умолчанию | Описание |", "| --- | --- | --- | --- |"]
    for dotted, field in _field_rows():
        kind = str(field.annotation).replace("typing.", "").replace("<class '", "").replace("'>", "")
        kind = kind.replace(" | ", r" \| ")  # a bare pipe would split the markdown table cell
        default = "—" if field.default is None else f"`{_toml_literal(field.default)}`"
        lines.append(f"| `{dotted}` | `{kind}` | {default} | {field.description} |")
    return "\n".join(lines) + "\n"
