---
name: repomix
description: Use when researching the OC8 repository, locating relevant files, understanding architecture boundaries, or needing generated Repomix context packs for backend, frontend, capas, deployment, or UI/API contracts.
---

# Repomix repository context

Use this skill for repository research before broad code searches or cross-cutting changes.

1. Read `AI_CONTEXT_INDEX.md` first. Paths in this skill are relative to this skill directory.
2. Choose the smallest context packs that match the task.
3. Use the selected packs as a map to find source files; verify facts against live source files before editing or reporting.

The bundled Repomix outputs are generated snapshots and may lag behind the working tree. Run `./update.sh` from this directory, or `.agents/skills/repomix/update.sh` from the repo root, to refresh them. `repomix.config.json` and `.repomixignore` are bundled here and used by `update.sh`.
