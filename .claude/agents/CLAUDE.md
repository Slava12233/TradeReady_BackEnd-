# .claude/agents/ — Sub-Agent Definitions

<!-- last-updated: 2026-04-06 -->

> 16 specialized sub-agents delegated to by the orchestrating Claude conversation for specific tasks.

## What This Directory Does

Contains YAML-frontmatter agent definition files that Claude Code can delegate work to. Each file specifies the agent's purpose, allowed tools, model, and full system prompt. Agents are invoked via the `Agent` tool from the parent conversation.

## Agent Inventory

| File | Category | Purpose |
|------|----------|---------|
| `code-reviewer.md` | Quality Gate | Reviews code against project CLAUDE.md standards after every change |
| `test-runner.md` | Quality Gate | Maps changed files to tests, runs them, writes missing tests |
| `context-manager.md` | Quality Gate | Maintains `development/context.md` and syncs all CLAUDE.md files |
| `security-auditor.md` | Security | Read-only audit for auth bypasses, injection risks, secret exposure |
| `security-reviewer.md` | Security | Vulnerability detection AND remediation — fixes CRITICAL issues directly |
| `migration-helper.md` | Infrastructure | Generates/validates Alembic migrations safely |
| `api-sync-checker.md` | Infrastructure | Compares Pydantic schemas vs TypeScript types, verifies route sync |
| `deploy-checker.md` | Infrastructure | Full A-Z deployment readiness: lint, types, tests, migrations, builds |
| `doc-updater.md` | Infrastructure | Syncs docs, CLAUDE.md files, and SDK docs with actual code |
| `perf-checker.md` | Infrastructure | Detects N+1, blocking async, missing indexes, React render issues |
| `backend-developer.md` | Development | Writes production-quality async Python 3.12+ following project conventions |
| `frontend-developer.md` | Development | Implements Next.js 16 / React 19 / Tailwind v4 features |
| `ml-engineer.md` | Development | RL training pipelines, GA, regime classifiers, ensemble systems |
| `e2e-tester.md` | Development | Live E2E scenarios — creates accounts, agents, trades, backtests, battles |
| `planner.md` | Research/Planning | Creates detailed phased implementation plans (uses opus model) |
| `codebase-researcher.md` | Research/Planning | Investigates codebase — answers questions, traces data flows |

## Agent Configuration Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Lowercase with hyphens (e.g., `code-reviewer`) |
| `description` | yes | When to delegate — trigger phrases for auto-delegation |
| `tools` | yes | Allowlist: `Read`, `Write`, `Edit`, `Grep`, `Glob`, `Bash` |
| `model` | no | `sonnet` (default), `opus` (for planning) |
| `memory` | no | `project` — enables cross-session learning via MEMORY.md files |

All 16 agents currently have `memory: project` enabled.

## Agent Memory

Each agent has a corresponding memory directory at `.claude/agent-memory/{agent-name}/` containing:
- `MEMORY.md` — seeded project patterns, conventions, and known gotchas
- Agent-specific memory files written during runs (feedback, project facts, user preferences)

## Pipelines (Execution Order)

Agents form pipelines that must run in order:

```
Standard post-change: code-reviewer → test-runner → context-manager
API/schema change: api-sync-checker → doc-updater → code-reviewer → test-runner → context-manager
Security-sensitive: security-reviewer (fix) → security-auditor (verify) → code-reviewer → test-runner → context-manager
Performance-sensitive: perf-checker → code-reviewer → test-runner → context-manager
Database migration: migration-helper → [apply] → deploy-checker → context-manager
Feature implementation: planner → codebase-researcher → [developer] → code-reviewer → test-runner → context-manager
```

## Patterns

- Read-only agents (auditor, sync-checker, perf-checker, planner, researcher) do NOT have Write/Edit tools
- `context-manager` is ALWAYS the final step of every task — never optional
- `planner` uses `opus` model for deeper reasoning on architecture decisions
- All agents load relevant CLAUDE.md files as first step in their workflow

## Gotchas

- Agent descriptions must include trigger phrases — without them auto-delegation won't fire
- `security-auditor` is read-only reports only; use `security-reviewer` to actually fix issues
- Agents do NOT share state between runs — pass context explicitly via prompt or file references
- Tool allowlists are strict — adding tools expands attack surface and should be intentional

## Recent Changes

- `2026-03-21` — All 16 agents enabled with `memory: project` as part of Agent Memory & Learning System (14 tasks)
- `2026-03-21` — Memory Protocol section added to all 16 agent system prompts
- `2026-03-21` — Initial CLAUDE.md created
- `2026-03-20` — Agent fleet expanded to 16 agents (was 12); categorized into 4 groups
- `2026-03-17` — Initial agent fleet created (12 agents)
