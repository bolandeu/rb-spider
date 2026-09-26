# Changelog

Все заметные изменения фиксируются здесь. Формат —
[Keep a Changelog](https://keepachangelog.com/), версии следуют
[SemVer](https://semver.org/). Записи добавляются в `Unreleased` в том же
коммите, что и изменение.

## [Unreleased]

### Added

- Каркас CLI `spider` (пакет `rb-spider`) по архитектуре `cli-builder`: `doctor`, `init`, `status`, `config list|get|set`, `auth login|logout|status`, `skill install`, `--json`/`--ai`/`--version`, фиксированные коды выхода, секреты в системном хранилище ключей.
- Справка всех команд на русском с примерами и формой `--json`; тесты: у каждой команды есть docstring, у каждой опции `help=`, снимки `--help` каждой команды.
