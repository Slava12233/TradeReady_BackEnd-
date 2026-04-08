# Context Manager Agent Memory

## Primary Files to Maintain

- `development/context.md` — rolling development log, always read first
- Every folder's `CLAUDE.md` — navigation file for that module

## CLAUDE.md Hierarchy (70 files total, as of 2026-03-22)

See [reference_claudemd_hierarchy.md](reference_claudemd_hierarchy.md) for full listing by area (backend 24, tests 3, frontend 22, agent 11, infra 10).

## context.md Structure

```
## Current State        <- always update first; this is what new conversations read
## Recent Activity      <- one dated session block per work session, most recent first
## Project Overview     <- stable; only update when architecture changes
```

**Current State fields:** Active work / Last session / Next steps / Blocked

## Naming Conventions for Milestones (context.md timeline)

Pattern seen in `development/CLAUDE.md` timeline entries:
- `YYYY-MM-DD — <Component/Phase> complete.` followed by component list + test count
- Use past tense ("complete", "added", "fixed")
- Include test counts when significant (e.g., "370+ tests", "578 tests")
- Reference task board when applicable (e.g., "Tasks 01-20", "23-task deployment board")

## CLAUDE.md Update Rules

**What must be updated after every code change:**
1. `<!-- last-updated: YYYY-MM-DD -->` timestamp
2. `## Key Files` table — add new files, remove deleted ones
3. `## Recent Changes` section — add dated entry
4. Public API section — if new classes/functions/endpoints added

**What NOT to update:**
- `## Gotchas` — only add, never remove (historical record)
- `## Patterns` — only add when a new genuine pattern is established

**Creating a new CLAUDE.md:**
- Minimum 2+ meaningful files (`.py`, `.tsx`, `.ts`) in the directory
- Skip: `__pycache__`, `node_modules`, `.venv`, `.next`, `build`, `dist`, init-only dirs
- Add row to root CLAUDE.md index table AND parent CLAUDE.md sub-file index

## Pruning Rules for context.md

- Last 7 days: full detail
- Last 30 days: one paragraph per session
- Older than 30 days: archive or delete
- Never prune Decisions or Learnings sections
- Prune only change logs when file exceeds 500 lines

## Known Completed Since Last Update

- `Frontend/src/components/battles/` — fully built (2026-03-22): 7 components, 2 routes, 2 hooks, 14 API functions, 15 types. Live battle crash fixed (2026-04-07).
- Agent ecosystem (Phase 1+2) complete — all CLAUDE.md files exist for `agent/conversation/`, `agent/memory/`, `agent/permissions/`, `agent/trading/`

## Root CLAUDE.md Index Tables

The root `CLAUDE.md` has separate index tables for:
- Backend (`src/`) modules
- Tests
- Frontend (`Frontend/`) modules — split into lib/hooks/stores/styles + components by feature
- Infrastructure & Other
- Sub-agents (`.claude/agents/`)
- Skills (`.claude/skills/`)

When adding a new CLAUDE.md, insert into the correct table section.

## Linked Memory Files

- [project_agent_ecosystem_complete.md](project_agent_ecosystem_complete.md) — Agent ecosystem (36 tasks, 2 phases) complete as of 2026-03-21; next focus is deployment and battle frontend

## Notes

- Agent Memory & Learning System (14 tasks) complete as of 2026-03-21; all 16 agents now have `memory: project` enabled
- New CLAUDE.md files created: `.claude/agents/CLAUDE.md`, `.claude/skills/CLAUDE.md`, `.claude/agent-memory/CLAUDE.md`
- `/analyze-agents` skill added; `/review-changes` updated with feedback capture
- 3 activity logging scripts added to `scripts/`
- Agent Logging System (34 tasks) complete as of 2026-03-21; `monitoring/CLAUDE.md` created (new directory)
- Alembic head is now 022 (021 after QA sprint, 022 after backtest stop_price fix 2026-04-07); DB now has 35+ tables including agent_api_calls, agent_strategy_signals, backtest_trades.stop_price
- `src/monitoring/metrics.py` created (new file in existing directory — update `src/monitoring/CLAUDE.md` when working there)
- 3 new API endpoints added to agents router (trace, analyze, feedback PATCH); agents.py now has 17 endpoints
- [project_master_plan_progress.md](project_master_plan_progress.md) — Trading Agent Master Plan task completion status and test counts by phase
- [feedback_claude_md_already_updated.md](feedback_claude_md_already_updated.md) — Sub-module CLAUDE.md files are updated inline by task agents; verify before re-updating
