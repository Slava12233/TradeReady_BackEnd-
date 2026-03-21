---
name: sync-context
description: "Scan every CLAUDE.md context file in the project, compare against the actual codebase, and update any that are stale — fix file inventories, test counts, API surfaces, timestamps, and the root index."
disable-model-invocation: true
---

# Sync All CLAUDE.md Context Files

Go through **every CLAUDE.md file** in this project and bring them up to date with the actual codebase. These are codebase navigation/context files, not documentation. Actually edit the files.

## Process

### 1. Find all CLAUDE.md files
Use Glob to find every `**/CLAUDE.md` in the project.

### 2. For each CLAUDE.md, compare and fix:

**File inventories** — Read the "Key Files" tables. Glob the directory for actual files. Add any new files missing from the table. Remove entries for deleted files.

**Test counts** — If the file mentions test counts, count the actual test files and update the numbers.

**Public API / class docs** — If the file documents classes, functions, or endpoints, grep the source code to verify they still exist and check for new ones.

**`<!-- last-updated -->` timestamp** — Update to today's date on every file you modify.

**Root CLAUDE.md index** — Make sure the index table lists every CLAUDE.md that exists on disk. Add missing entries. Remove entries for files that no longer exist.

### 3. Report what you changed
```
Synced X CLAUDE.md files:
- path/to/CLAUDE.md — added 3 new files, updated test count
- path/to/CLAUDE.md — removed deleted file entry
- CLAUDE.md (root) — added new module to index
No changes needed for Y files.
```

## Rules
- Actually edit the files — don't just report what's wrong
- Preserve the existing writing style and structure of each file
- Don't rewrite sections that are already correct
- Only add/remove/update what's actually changed
- Update the `<!-- last-updated -->` date on every file you touch
- Keep it fast — use Glob and Grep to spot-check, don't read every source file line by line
