---
type: moc
title: Wikilink Conventions
tags:
  - moc
  - conventions
---

# Wikilink Conventions

Standards for `[[wikilinks]]` in the development vault. Both humans and agents follow these rules.

## Scope

Wikilinks are used **only in `development/` files**. Never in:
- CLAUDE.md files (agent navigation system, standard markdown only)
- Source code comments
- `.claude/` agent or skill files

## Link Targets

| Target Type | Format | Example |
|-------------|--------|---------|
| Root-level doc | `[[file-name]]` | `[[context]]`, `[[agent-ecosystem-plan]]` |
| Task board | `[[board-slug/README\|Display Name]]` | `[[agent-memory-system/README\|Agent Memory Board]]` |
| Individual task | `[[board-slug/task-file\|Task N]]` | `[[agent-strategies/task-01-ppo-rl-strategy\|Task 01]]` |
| Code review | `[[review-file\|Short Name]]` | `[[review_2026-03-20_16-24_frontend-perf-fixes\|Frontend Perf Review]]` |
| Section link | `[[file#Section]]` | `[[context#Current State]]` |
| Daily note | `[[YYYY-MM-DD]]` | `[[2026-03-21]]` |
| MOC | `[[moc-name]]` | `[[task-boards-moc]]` |

## Rules

1. **Use pipe aliases for readability**: `[[long-file-name|Short Name]]`
2. **No wikilinks to source code**: Reference files as inline code: `` `src/agents/service.py` ``
3. **Folder-scope task links** to avoid collisions across boards
4. **Prefer `[[context]]`** over `[[context.md]]` (Obsidian resolves both, but shorter is better)
5. **Section links** use `#` syntax: `[[context#Key Design Decisions]]`

## Tag Conventions

Tags use slash-separated categories:

| Category | Examples |
|----------|---------|
| Content type | `task`, `review`, `plan`, `research`, `daily`, `moc` |
| Module | `frontend`, `backend`, `agent`, `ml`, `strategies` |
| Status | `active`, `archived`, `done`, `pending` |

## Agent Output

When agents create files in `development/`, they should:
1. Include YAML frontmatter with `type` and `tags`
2. Use `[[wikilinks]]` for cross-references to other vault files
3. Never add wikilinks to files outside `development/`
