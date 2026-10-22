# AGENTS.md

Pointers for agents. Antagor shows the changing state (statuses, branches, tasks): `antagor board`.

- What the project is, and the domain glossary: `CONTEXT.md`. Take terms only from there.
- Decisions and why: `docs/adr/` (format: `docs/adr/README.md`).
- Code rules for review: `CODING_STANDARDS.md`.
- Правила разработки spider (стенд, база, TDD, документация команд, соседние пакеты): `docs/dev.md`; решения — `docs/spec.md`, чеклист функций — `docs/features.md`.
- Antagor keeps the tasks and epics: `.agents/antagor/`.
- How to write to the Human and to agents (ASD-STE100): the skill `antagor-method`, section «How to write to the Human and to agents».
- The package Standard: https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator/src/branch/main/skills/cli-builder/reference/standard.md (sections by name, for example «Install»).
- The gate before a commit: the `rb-release check` step of `.gitea/workflows/ci.yml` — run that command.

## Architect only

A worker does not need this section: Antagor cuts it from the worker's brief.
