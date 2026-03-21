---
type: execution-guide
title: Obsidian Integration Execution Guide
board: "[[obsidian-integration/README]]"
tags:
  - execution-guide
  - obsidian
---

# Obsidian Integration -- Execution Guide

This guide defines how to execute the 32 tasks in the Obsidian Knowledge Management Integration board. Tasks are organized into 7 parallel groups (A-G) that must be executed in order, but tasks within each group can run in parallel.

---

## Prerequisites

- All agents listed in `.claude/agents/` are available
- The `development/` directory exists with existing task boards, code reviews, and planning docs
- Git repo is on the `V.0.0.2` branch

## Agents Required

| Agent | Role | Task Count |
|-------|------|------------|
| `backend-developer` | Primary implementer | 23 |
| `context-manager` | Agent prompt updates, final context update | 3 |
| `doc-updater` | Documentation and workflow guides | 3 |
| `code-reviewer` | Quality gate (review pass) | 1 |
| `test-runner` | Quality gate (test pass) | 1 |

---

## Execution Order

### Group A: Foundation (no dependencies)

**Run first. All other groups depend on Task 01.**

| Order | Task | Agent | Notes |
|-------|------|-------|-------|
| 1 | Task 01: Create Obsidian vault config | `backend-developer` | Must complete before anything else |
| 2 (parallel) | Task 02: Create vault directory structure | `backend-developer` | After Task 01 |
| 2 (parallel) | Task 03: Update .gitignore | `backend-developer` | After Task 01 |

**Checkpoint:** Verify `development/.obsidian/` exists with valid JSON configs. Opening `development/` in Obsidian should recognize it as a vault.

---

### Group B: Frontmatter Enrichment (after Group A)

**All tasks depend on Task 01. Tasks 04, 05, 07, 08 can run in parallel. Task 06 must wait for Task 05.**

| Order | Task | Agent | Notes |
|-------|------|-------|-------|
| 1 (parallel) | Task 04: Code review frontmatter | `backend-developer` | 9 files |
| 1 (parallel) | Task 05: Task board README frontmatter | `backend-developer` | 6 files |
| 1 (parallel) | Task 07: Planning doc frontmatter | `backend-developer` | 30+ files |
| 1 (parallel) | Task 08: context.md frontmatter | `backend-developer` | 1 file |
| 2 | Task 06: Individual task file frontmatter | `backend-developer` | 110+ files, after Task 05 |

**Checkpoint:** Run YAML validation on all `development/**/*.md` files. All frontmatter should parse cleanly.

---

### Group C: Cross-References + Plugin Configs (after Group B)

**Tasks 09, 12, 19 can run in parallel. Tasks 10, 11 have specific dependencies.**

| Order | Task | Agent | Notes |
|-------|------|-------|-------|
| 1 (parallel) | Task 09: Wikilink conventions | `backend-developer` | After Phase 2 |
| 1 (parallel) | Task 12: Configure Templater | `backend-developer` | After Task 01 |
| 1 (parallel) | Task 19: Configure Dataview | `backend-developer` | After Task 01 |
| 2 (parallel) | Task 10: Task board wikilinks | `backend-developer` | After Tasks 05, 09 |
| 2 (parallel) | Task 11: Code review wikilinks | `backend-developer` | After Tasks 04, 09 |

**Checkpoint:** Wikilink conventions file exists. Plugin directories have valid configs.

---

### Group D: Templates + MOCs (after Group C)

**Tasks 13, 14, 15 can run in parallel (after Task 12). MOCs are sequential.**

| Order | Task | Agent | Notes |
|-------|------|-------|-------|
| 1 (parallel) | Task 13: Code review template | `backend-developer` | After Task 12 |
| 1 (parallel) | Task 14: Task file template | `backend-developer` | After Task 12 |
| 1 (parallel) | Task 15: Other templates | `backend-developer` | After Task 12 |
| 2 | Task 16: Root MOC | `backend-developer` | After Phase 2 |
| 3 | Task 17: Topic MOCs | `backend-developer` | After Task 16 |
| 4 | Task 18: Agent fleet MOC | `backend-developer` | After Task 17 |

**Checkpoint:** All templates exist in `_templates/`. All MOCs exist in `_moc/`. Graph view should show connected clusters.

---

### Group E: Dashboards + Daily Notes (after Group D)

**Tasks 20, 21, 22 can run in parallel. Tasks 23, 24 depend on Task 22.**

| Order | Task | Agent | Notes |
|-------|------|-------|-------|
| 1 (parallel) | Task 20: Project health dashboard | `backend-developer` | After Tasks 04-08, 19 |
| 1 (parallel) | Task 21: Agent activity dashboard | `backend-developer` | After Tasks 18, 19 |
| 1 (parallel) | Task 22: Seed daily notes | `backend-developer` | After Task 15 |
| 2 (parallel) | Task 23: Daily note workflow docs | `doc-updater` | After Task 22 |
| 2 (parallel) | Task 24: Daily note script | `backend-developer` | After Task 22 |

**Checkpoint:** Dashboards render in Obsidian (Dataview queries execute). Daily notes exist for 2026-03-18 through 2026-03-21.

---

### Group F: Git Plugin + Agent Updates (after Group E)

**Tasks 25, 27, 28, 29 can run in parallel. Task 26 depends on Task 25.**

| Order | Task | Agent | Notes |
|-------|------|-------|-------|
| 1 (parallel) | Task 25: Obsidian Git config | `backend-developer` | After Task 01 |
| 1 (parallel) | Task 27: Code-reviewer update | `context-manager` | After Phase 4 |
| 1 (parallel) | Task 28: Context-manager update | `context-manager` | After Tasks 22, 24 |
| 1 (parallel) | Task 29: plan-to-tasks update | `backend-developer` | After Task 14 |
| 2 | Task 26: Git workflow docs | `doc-updater` | After Task 25 |

**Checkpoint:** Agent prompts include frontmatter instructions. Git plugin config exists.

---

### Group G: Quality Gate (final, after all)

**Sequential execution. This is the mandatory post-change pipeline.**

| Order | Task | Agent | Notes |
|-------|------|-------|-------|
| 1 | Task 30: Code review + testing | `code-reviewer`, `test-runner` | After ALL tasks |
| 2 | Task 31: Update development/CLAUDE.md | `doc-updater` | After Task 30 |
| 3 | Task 32: Context manager final update | `context-manager` | After Task 31 (FINAL) |

**Checkpoint:** All validation passes. CLAUDE.md updated. context.md has milestone entry.

---

## How to Run

### Option 1: Manual execution with Claude Code

For each group, delegate tasks to the assigned agents:

```
# Group A
@backend-developer Execute Task 01, then Tasks 02 and 03 in parallel

# Group B (after Group A completes)
@backend-developer Execute Tasks 04, 05, 07, 08 in parallel, then Task 06

# ... continue through groups
```

### Option 2: Single-agent sequential execution

Run all tasks sequentially with a single `backend-developer` agent for the bulk work, then hand off to specialized agents:

1. Tasks 01-22, 24-25, 29 -> `backend-developer`
2. Task 23 -> `doc-updater`
3. Task 26 -> `doc-updater`
4. Tasks 27-28 -> `context-manager`
5. Task 30 -> `code-reviewer` then `test-runner`
6. Task 31 -> `doc-updater`
7. Task 32 -> `context-manager`

### Tracking Progress

Update each task file's `status` field as work progresses:
- `pending` -> `in-progress` -> `done` (or `blocked`)

The README.md task index table should be updated to reflect current status.

---

## Risk Summary

| Risk | Mitigation |
|------|------------|
| Corrupted existing YAML frontmatter | Task 06 must preserve existing fields; validate after |
| Broken wikilinks | Task 30 validation checks all `[[...]]` resolve to files |
| CLAUDE.md contamination with wikilinks | Task 30 checks no CLAUDE.md has `[[` |
| Git conflicts from Obsidian Git auto-pull | `autoSaveInterval: 0` (disabled); only `context.md` is shared mutable |
| Agent workflows break | Only prompt-level changes (Tasks 27-29); no source code modified |

---

## Success Criteria

1. `development/` opens as a valid Obsidian vault
2. Graph view shows connected nodes (reviews -> plans -> tasks)
3. Dataview dashboards render correctly
4. Daily notes system works (both manual and script-generated)
5. All existing tests pass (`pytest tests/`)
6. No CLAUDE.md files contain wikilinks
7. All YAML frontmatter is valid
8. Agent pipelines still function correctly
