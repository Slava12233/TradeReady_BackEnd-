# .claude/skills/ — Reusable Skill Workflows

<!-- last-updated: 2026-03-23 -->

> Slash-command workflows invoked with `/skill-name` to run multi-step tasks.

## What This Directory Does

Contains skill subdirectories, each with a `SKILL.md` file that defines a reusable workflow invoked as a slash command. Skills are higher-level than agents — they orchestrate multiple agents, run quality pipelines, and automate repetitive multi-step workflows.

## Skill Inventory

| Skill | Command | File | Purpose |
|-------|---------|------|---------|
| `commit` | `/commit` | `commit/SKILL.md` | Smart commit: stages files, generates conventional message (`type(scope): desc`), runs ruff check, commits |
| `review-changes` | `/review-changes` | `review-changes/SKILL.md` | Full post-change pipeline: detects pipeline type, runs agents in order (code-reviewer → test-runner → context-manager + extras). Now includes feedback capture. |
| `run-checks` | `/run-checks` | `run-checks/SKILL.md` | Quick quality gate: ruff + mypy + pytest on changed files only. Fast feedback, no agent delegation |
| `sync-context` | `/sync-context` | `sync-context/SKILL.md` | Scan all CLAUDE.md files, fix stale inventories, create missing ones, update development/context.md |
| `plan-to-tasks` | `/plan-to-tasks <file>` | `plan-to-tasks/SKILL.md` | Read a plan file, discover agents, match tasks to agents, create task files in `development/tasks/` |
| `analyze-agents` | `/analyze-agents` | `analyze-agents/SKILL.md` | Analyze agent activity logs and memory files to generate improvement report in `development/agent-analysis/` |
| `c-level-report` | `/c-level-report` | `c-level-report/SKILL.md` | Generates comprehensive C-level executive reports with real-time metrics (KPIs, risk, roadmap). Saves to `development/C-level_reports/` |

## Patterns

- Skills are stored as subdirectories, not flat files — each has its own `SKILL.md`
- Skills can delegate to agents via the `Agent` tool
- `review-changes` is the most important skill — it runs the mandatory post-change pipeline
- `analyze-agents` reads `development/agent-activity-log.jsonl` (written by PostToolUse hook)

## Gotchas

- Skills with `user-invocable: true` in frontmatter show up in the slash command palette
- `review-changes` detects the pipeline type automatically (standard, API change, security, perf) — don't specify manually
- `run-checks` is the fast path; `review-changes` is the full pipeline — use run-checks for rapid iteration, review-changes before committing
- `analyze-agents` creates `development/agent-analysis/` directory automatically if it doesn't exist

## Recent Changes

- `2026-03-23` — `/c-level-report` skill created. Files: `SKILL.md`, `templates/report-template.md`, `examples/sample-report.md`. Tools: Read, Write, Grep, Glob, Bash. Output: `development/C-level_reports/report-YYYY-MM-DD.md`
- `2026-03-21` — `/analyze-agents` skill created (Task 13 of Agent Memory & Learning System)
- `2026-03-21` — `/review-changes` updated with feedback capture (Task 14 of Agent Memory & Learning System)
- `2026-03-21` — Initial CLAUDE.md created
- `2026-03-17` — Skills directory created with initial 5 skills
