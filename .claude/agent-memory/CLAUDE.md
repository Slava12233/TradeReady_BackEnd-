# .claude/agent-memory/ — Agent Memory Storage

<!-- last-updated: 2026-04-06 -->

> Persistent cross-session memory for all 16 sub-agents. Each subdirectory stores one agent's MEMORY.md plus any typed memory files.

## What This Directory Does

Provides file-based memory persistence for the agent fleet. Each agent subdirectory contains a `MEMORY.md` index and individual typed memory files (`user_*.md`, `feedback_*.md`, `project_*.md`, `reference_*.md`). Memory is loaded at the start of each agent run and updated when new patterns are learned.

## Directory Structure

```
agent-memory/
  {agent-name}/
    MEMORY.md                    — index of all memory files (always loaded)
    user_{topic}.md              — user role, preferences, knowledge
    feedback_{topic}.md          — guidance: what to avoid, what to repeat
    project_{topic}.md           — ongoing work, goals, blockers
    reference_{topic}.md         — pointers to external resources
```

## Agent Memory Directories (16 total)

| Agent | Status | Notes |
|-------|--------|-------|
| `code-reviewer/` | Seeded | Quality gate patterns, test standards, project conventions |
| `test-runner/` | Seeded | Test framework, async patterns, mock patterns |
| `context-manager/` | Seeded + active | Has additional `project_agent_ecosystem_complete.md` |
| `security-auditor/` | Seeded | OWASP patterns, auth patterns, project-specific security |
| `security-reviewer/` | Seeded | Critical fix patterns, Lua script atomicity, permission enforcement |
| `api-sync-checker/` | Seeded | Schema sync patterns, TypeScript type paths |
| `deploy-checker/` | Seeded | Deployment checklist, environment validation |
| `doc-updater/` | Seeded | Documentation structure, CLAUDE.md update rules |
| `perf-checker/` | Seeded | N+1 patterns, async gotchas, frontend perf patterns |
| `migration-helper/` | Seeded | Migration conventions, two-phase NOT NULL, hypertable rules |
| `backend-developer/` | Seeded | Python patterns, repo pattern, exception hierarchy |
| `frontend-developer/` | Seeded | Next.js conventions, component patterns, performance baseline |
| `ml-engineer/` | Seeded | RL/GA/ensemble patterns, tradeready-gym integration |
| `e2e-tester/` | Seeded | E2E test patterns, script inventory, live data requirements |
| `planner/` | Seeded | Planning conventions, task board format, agent pipelines |
| `codebase-researcher/` | Seeded | Research methodology, where to look for things |

## Memory File Format

```markdown
---
name: {memory name}
description: {one-line description for relevance matching}
type: {user, feedback, project, reference}
---

{memory content}
**Why:** {reason this matters}
**How to apply:** {when/where this kicks in}
```

## Patterns

- `MEMORY.md` in each subdirectory is the index — always loaded, kept under 200 lines
- Memory files are read-only from outside agents; only the owning agent should write to its directory
- `context-manager` agent has write access to ALL memory directories for seeding and maintenance
- Memory is version-controlled — shared across the team via git (unlike `settings.local.json`)

## Gotchas

- Memory that names specific file paths may go stale — always verify before acting on it
- `MEMORY.md` lines truncate after 200 — keep the index concise; put detail in individual files
- Ephemeral task state should NOT go in memory — use task files for in-conversation tracking
- Agent-memory-local/ (excluded from git via .gitignore) is for personal/private memory overrides

## Recent Changes

- `2026-03-21` — All 16 agent memory directories created and seeded (Tasks 01-06 of Agent Memory & Learning System)
- `2026-03-21` — Memory Protocol added to all 16 agent prompts (Task 07)
- `2026-03-21` — Initial CLAUDE.md created
