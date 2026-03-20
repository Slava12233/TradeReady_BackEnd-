---
name: sync-context
description: "Scan every CLAUDE.md context file in the project, compare against the actual codebase, and update any that are stale — fix file inventories, test counts, API surfaces, timestamps, and the root index. Also create new CLAUDE.md files for directories that should have one but don't. Finally, update development/context.md with any changes made during this session."
disable-model-invocation: true
---

# Sync All CLAUDE.md Context Files + Development Context

Go through **every CLAUDE.md file** in this project and bring them up to date with the actual codebase. Also **create new CLAUDE.md files** for directories that should have one but don't yet. Finally, **update `development/context.md`** to reflect the current state. These are codebase navigation/context files, not documentation. Actually edit the files.

## Process

### 1. Find all CLAUDE.md files
Use Glob to find every `**/CLAUDE.md` in the project (exclude `.venv/`, `node_modules/`).

### 2. Find directories that SHOULD have a CLAUDE.md but don't

Scan for directories that contain meaningful code or config but lack a CLAUDE.md:

**Backend** — Glob `src/*/` and `src/*/*/` for directories with `.py` files. Every directory with 2+ Python files (excluding `__pycache__`) should have a CLAUDE.md.

**Frontend** — Glob `Frontend/src/components/*/`, `Frontend/src/*/` for directories with `.tsx`/`.ts` files. Every component group directory should have a CLAUDE.md.

**Top-level packages** — Check `agent/`, `sdk/`, `tradeready-gym/`, `scripts/`, `docs/`, `alembic/`, `tests/` and their meaningful subdirectories.

**Skip** — `__pycache__`, `node_modules`, `.venv`, `.next`, `build`, `dist`, `.ruff_cache`, `reports/`, directories with only `__init__.py`.

### 3. Create missing CLAUDE.md files

For each directory identified in step 2 that lacks a CLAUDE.md:

1. **Read 2-3 existing CLAUDE.md files** in sibling or parent directories to match their tone and structure
2. **Glob the directory** to get all files
3. **Create the CLAUDE.md** following the project template:

```markdown
# {Module Name}

<!-- last-updated: YYYY-MM-DD -->

> One-line purpose of this module.

## What This Module Does
2-3 sentence overview.

## Key Files
| File | Purpose |
|------|---------|
| `file.py` | What it does |

## Public API / Key Exports
Key classes, functions, or endpoints exposed by this module.

## Patterns
- Key patterns used in this directory

## Gotchas
- Non-obvious things

## Recent Changes
- `YYYY-MM-DD` — Initial creation
```

4. **Add to root CLAUDE.md index** — Insert a row in the appropriate index table
5. **Add to parent CLAUDE.md** — If the parent directory has a CLAUDE.md with a sub-file index, add a reference

### 4. For each EXISTING CLAUDE.md, compare and fix:

**File inventories** — Read the "Key Files" or "Script Inventory" tables. Glob the directory for actual files. Add any new files missing from the table. Remove entries for deleted files.

**Test counts** — If the file mentions test counts (e.g., "62 files, 974 tests"), count the actual test files in that directory and update the numbers.

**Public API / class docs** — If the file documents classes, functions, or endpoints, grep the source code to verify they still exist and check for new ones that should be added.

**`<!-- last-updated -->` timestamp** — Update to today's date on every file you modify.

**Root CLAUDE.md index** — Make sure the index table in the root `CLAUDE.md` lists every CLAUDE.md that exists on disk. Add missing entries. Remove entries for files that no longer exist.

### 5. Update `development/context.md`

This is the rolling development log maintained by the `context-manager` agent. After syncing CLAUDE.md files, update it:

1. **Read `development/context.md`** to understand the current format and sections
2. **Update "Current State"** block at the top:
   - Check `git log --oneline -20` for recent commits since the last session entry
   - Update "Last session" date and summary if work was done today
   - Update "Next steps" if priorities have changed
   - Update "Blocked" if anything is blocked or unblocked
3. **Update "What's Built" table** if any new systems/modules were added or status changed
4. **Update tech stack** section if dependencies changed (check `pyproject.toml`, `package.json`)
5. **Update test counts** in the tech stack section — run `find tests/ -name "test_*.py" | wc -l` and grep for test function counts
6. **Update "Sub-Agent Fleet"** table if new agents were added to `.claude/agents/`
7. **Add a new session entry** under "Recent Activity" if significant work happened since the last entry:
   - Use the format: `### YYYY-MM-DD — Brief Title`
   - Include: Changes (bullet list of files), Decisions (with reasoning), Learnings, Bugs fixed
   - Only add an entry if there are meaningful changes to document — don't create empty entries
8. **Do NOT rewrite existing entries** — only append new ones or update the Current State block

### 6. Report what you changed
After updating, print a short summary:
```
Synced X CLAUDE.md files:
- src/foo/CLAUDE.md — added 3 new files, updated test count
- src/bar/CLAUDE.md — removed deleted file entry
- CLAUDE.md (root) — added src/exchange/CLAUDE.md to index

Created Y new CLAUDE.md files:
- src/new-module/CLAUDE.md — new module (5 files)
- agent/tools/CLAUDE.md — new subdirectory (3 files)

Updated development/context.md:
- Current State: updated last session date
- What's Built: added new-module row
- Recent Activity: added 2026-03-20 session entry

No changes needed for Z files.
```

## Rules
- Actually edit the files — don't just report what's wrong
- Preserve the existing writing style and structure of each file
- Don't rewrite sections that are already correct
- Only add/remove/update what's actually changed
- Update the `<!-- last-updated -->` date on every file you touch
- Keep it fast — don't read every source file line by line, use Glob and Grep to spot-check
- For new CLAUDE.md files, match the style of nearby existing ones
- Don't create CLAUDE.md for trivial directories (only `__init__.py`, or empty)
- Always add newly created CLAUDE.md files to the root index
