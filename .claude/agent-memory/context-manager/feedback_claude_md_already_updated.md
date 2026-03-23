---
name: Sub-module CLAUDE.md files are updated inline by task agents
description: When task agents complete work, they update the relevant sub-module CLAUDE.md before handing off. Always read the file first to see if it is already current.
type: feedback
---

When tasks complete and the context-manager is called, the sub-module CLAUDE.md files (e.g., `agent/strategies/regime/CLAUDE.md`, `agent/strategies/risk/CLAUDE.md`) have often already been updated by the task agent as part of the work. Always read the file before deciding to update it.

**Why:** In the 2026-03-22 session, regime/CLAUDE.md, risk/CLAUDE.md, ensemble/CLAUDE.md, rl/CLAUDE.md, and tools/CLAUDE.md were all already correct when the context-manager ran. Only `agent/strategies/CLAUDE.md` (the parent file) and `agent/CLAUDE.md` (top-level) needed updates because they aggregate sub-module info that was not automatically synced.

**How to apply:** For each set of task completions, first read the sub-module CLAUDE.md to verify it reflects the changes described. Only update if the file is stale. Always update the parent/aggregate CLAUDE.md files (`agent/strategies/CLAUDE.md`, `agent/CLAUDE.md`) since task agents typically don't update those.
