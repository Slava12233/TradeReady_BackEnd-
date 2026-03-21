# Claude Code Starter Kit

A drop-in template package that gives any project a complete Claude Code agentic layer — CLAUDE.md navigation files, 16 custom agents with persistent memory, 7 skills, activity logging, rules, settings, and execution pipelines.

## What's Inside

```
claude-code-starter-kit/
├── README.md                              # This file
├── SETUP-INSTRUCTIONS.md                  # Step-by-step bootstrap guide
├── templates/
│   ├── ROOT-CLAUDE.md.template            # Root CLAUDE.md (copy to project root)
│   ├── MODULE-CLAUDE.md.template          # Sub-module CLAUDE.md template
│   ├── settings.json                      # Project .claude/settings.json (shared, committed)
│   ├── settings.local.json.example        # Local overrides (gitignored)
│   ├── agents/                            # 16 custom sub-agents
│   │   ├── code-reviewer.md              # Reviews code against project standards
│   │   ├── test-runner.md                # Runs tests, writes missing tests
│   │   ├── context-manager.md            # Maintains rolling dev context log
│   │   ├── planner.md                    # Plans complex features (Opus model)
│   │   ├── codebase-researcher.md        # Researches codebase to answer questions
│   │   ├── security-reviewer.md          # Audits + fixes security vulnerabilities
│   │   ├── security-auditor.md           # Read-only security audit
│   │   ├── perf-checker.md               # Performance regression detection
│   │   ├── deploy-checker.md             # Deployment readiness validation
│   │   ├── doc-updater.md                # Keeps docs in sync with code
│   │   ├── api-sync-checker.md           # Backend/frontend API sync verification
│   │   ├── migration-helper.md           # Database migration safety validation
│   │   ├── e2e-tester.md                 # End-to-end live testing
│   │   ├── frontend-developer.md         # Frontend implementation agent
│   │   ├── backend-developer.md          # Backend implementation agent
│   │   └── ml-engineer.md               # ML/RL training pipeline agent
│   ├── skills/
│   │   ├── sync-context/SKILL.md         # Syncs all CLAUDE.md files with codebase
│   │   ├── bootstrap-project/SKILL.md    # One-shot: generates all CLAUDE.md files
│   │   ├── commit/SKILL.md              # Smart conventional commit
│   │   ├── review-changes/SKILL.md      # Full post-change agent pipeline + feedback
│   │   ├── run-checks/SKILL.md          # Quick lint + type + test checks
│   │   ├── plan-to-tasks/SKILL.md       # Converts plans to agent-assigned task files
│   │   └── analyze-agents/SKILL.md      # Analyze agent activity + suggest improvements
│   ├── scripts/
│   │   ├── log-agent-activity.sh         # PostToolUse hook — logs tool usage to JSONL
│   │   ├── agent-run-summary.sh          # Generates per-run change summaries
│   │   └── analyze-agent-metrics.sh      # CLI metrics from activity log (requires jq)
│   ├── rules/
│   │   ├── code-style.md                 # Language/framework style rules
│   │   ├── testing.md                    # Test conventions
│   │   └── security.md                   # Security standards
│   └── development/
│       ├── CLAUDE.md.template            # Development folder context file
│       └── context.md.template           # Rolling development log template
└── .gitignore-additions.txt              # Lines to add to your .gitignore
```

## How to Use

### Quick Start (5 minutes)

1. **Copy the templates into your project:**
   ```bash
   # From your project root:
   cp -r path/to/claude-code-starter-kit/templates/.  .claude/
   cp claude-code-starter-kit/templates/ROOT-CLAUDE.md.template ./CLAUDE.md
   mkdir -p development scripts
   cp claude-code-starter-kit/templates/development/* development/
   cp claude-code-starter-kit/templates/scripts/* scripts/
   chmod +x scripts/*.sh
   ```

2. **Run the bootstrap skill:**
   Open Claude Code in your project and run:
   ```
   /bootstrap-project
   ```
   This scans your codebase and generates CLAUDE.md files in every major directory.

3. **Claude Code auto-customizes everything:**
   The bootstrap skill will:
   - Detect your tech stack (language, framework, DB, package manager)
   - Generate CLAUDE.md files for every module
   - Customize agents to match your project conventions
   - Update the root CLAUDE.md with a complete module index

4. **Add `.gitignore` entries:**
   ```
   .claude/settings.local.json
   .claude/agent-memory-local/
   ```

### Manual Setup

See `SETUP-INSTRUCTIONS.md` for detailed step-by-step instructions.

## Agent Fleet Overview

### Quality Gate Agents (run after every change)

| Agent | Purpose | Tools | Model | Mode |
|-------|---------|-------|-------|------|
| `code-reviewer` | Reviews code against CLAUDE.md-documented standards | Read, Write, Grep, Glob, Bash | sonnet | report + write |
| `test-runner` | Maps changes to tests, runs them, writes missing tests | Read, Write, Edit, Grep, Glob, Bash | sonnet | run + write |
| `context-manager` | Maintains rolling dev log + syncs CLAUDE.md files | Read, Write, Edit, Grep, Glob, Bash | sonnet | write |

### Security Agents (run for auth/input/sensitive changes)

| Agent | Purpose | Tools | Model | Mode |
|-------|---------|-------|-------|------|
| `security-auditor` | Read-only security audit (auth, injection, secrets, XSS) | Read, Grep, Glob, Bash | sonnet | read-only |
| `security-reviewer` | Vulnerability detection + remediation (can fix CRITICALs) | Read, Write, Edit, Bash, Grep, Glob | sonnet | read + fix |

### Infrastructure Agents (run before deploys, migrations, API changes)

| Agent | Purpose | Tools | Model | Mode |
|-------|---------|-------|-------|------|
| `migration-helper` | Validates/generates database migrations for safety | Read, Write, Edit, Grep, Glob, Bash | sonnet | write |
| `api-sync-checker` | Compares backend schemas vs frontend types | Read, Grep, Glob, Bash | sonnet | read-only |
| `deploy-checker` | Full A-Z deployment readiness validation | Read, Write, Edit, Grep, Glob, Bash | sonnet | report + write |
| `doc-updater` | Keeps documentation in sync with code | Read, Write, Edit, Grep, Glob, Bash | sonnet | write |
| `perf-checker` | Performance regression detection (N+1, blocking async, indexes) | Read, Grep, Glob, Bash | sonnet | read-only |

### Development Agents (run when building features)

| Agent | Purpose | Tools | Model | Mode |
|-------|---------|-------|-------|------|
| `backend-developer` | Writes production-quality backend code | Read, Write, Edit, Grep, Glob, Bash | sonnet | write |
| `frontend-developer` | Implements frontend features following conventions | Read, Write, Edit, Grep, Glob, Bash | sonnet | write |
| `ml-engineer` | ML/RL training pipelines, model integration | Read, Write, Edit, Grep, Glob, Bash | sonnet | write |
| `e2e-tester` | Runs live E2E scenarios, returns credentials | Read, Write, Edit, Grep, Glob, Bash | sonnet | write |

### Research & Planning Agents (run before implementing)

| Agent | Purpose | Tools | Model | Mode |
|-------|---------|-------|-------|------|
| `planner` | Creates detailed phased implementation plans | Read, Grep, Glob | **opus** | read-only |
| `codebase-researcher` | Answers questions about codebase using CLAUDE.md nav | Read, Grep, Glob, Bash | sonnet | read-only |

## Agent Pipelines (Execution Order)

Agents form ordered pipelines — not independent tools:

```
Standard Post-Change (every code change):
  code-reviewer → test-runner → context-manager

API/Schema Change:
  api-sync-checker → doc-updater → code-reviewer → test-runner → context-manager

Security-Sensitive Change:
  security-reviewer → security-auditor → code-reviewer → test-runner → context-manager

Performance-Sensitive Change:
  perf-checker → code-reviewer → test-runner → context-manager

Database Migration:
  migration-helper → [apply] → deploy-checker → context-manager

Feature Implementation:
  planner → codebase-researcher → backend/frontend/ml-engineer → code-reviewer → test-runner → context-manager
```

## Skills (Slash Commands)

| Skill | Command | Description |
|-------|---------|-------------|
| `commit` | `/commit` | Smart commit: stages, lints, generates conventional message, commits |
| `review-changes` | `/review-changes` | Full post-change pipeline: auto-detects type, runs agents in order |
| `run-checks` | `/run-checks` | Quick quality gate: lint + type check + tests on changed files only |
| `sync-context` | `/sync-context` | Scan all CLAUDE.md files, fix stale data, create missing ones |
| `bootstrap-project` | `/bootstrap-project` | One-shot: scan codebase, generate all CLAUDE.md files, customize agents |
| `plan-to-tasks` | `/plan-to-tasks <file>` | Read a plan, match tasks to agents, create task files |
| `analyze-agents` | `/analyze-agents` | Analyze agent activity logs, memory health, suggest improvements |

## Mandatory Agent Rules

These rules go into your root `CLAUDE.md`:

1. **After ANY code change** → run standard pipeline: `code-reviewer` → `test-runner` → `context-manager`
2. **Before ANY migration** → `migration-helper`
3. **After API/schema changes** → `api-sync-checker` → `doc-updater` → standard pipeline
4. **For security-sensitive changes** → `security-reviewer` → `security-auditor` → standard pipeline
5. **For performance-sensitive changes** → `perf-checker` → standard pipeline
6. **`context-manager` is ALWAYS the final step** — not optional

## Advanced Agent Features

Agents support these advanced frontmatter fields:

| Field | Values | Purpose |
|-------|--------|---------|
| `memory` | `project` / `user` / `local` | Cross-session learning — agent remembers patterns across conversations |
| `effort` | `low` / `medium` / `high` / `max` | Controls reasoning depth — use `high` for planning/security |
| `isolation` | `worktree` | Runs in isolated git worktree copy |
| `maxTurns` | number | Limits agentic turns before stopping |
| `hooks` | object | PreToolUse/PostToolUse/Stop lifecycle hooks |

**Recommended assignments:**
- `memory: project` → **all 16 agents** (enabled by default in all templates)
- `effort: high` → `planner`, `security-reviewer`, `deploy-checker`
- `effort: medium` → most other agents (default)

## Agent Memory System

All 16 agents have `memory: project` enabled — they learn across conversations and persist knowledge in `.claude/agent-memory/<agent-name>/MEMORY.md`.

### How It Works

1. **Before each run**, agents read their `MEMORY.md` for patterns and learnings
2. **After completing work**, agents update `MEMORY.md` with new discoveries
3. **When memory exceeds 100 lines**, agents archive old entries to `old-memories/` as dated `.md` files
4. **Memory is git-committed** (`memory: project` scope) — shared with the team

### Activity Logging

A PostToolUse hook in `settings.json` automatically logs every Write/Edit/Bash tool call to `development/agent-activity-log.jsonl`:

```json
{"ts":"2026-03-21T10:30:00Z","tool":"Write","target":"src/api/routes.py"}
```

Three scripts support the logging pipeline:

| Script | Purpose |
|--------|---------|
| `scripts/log-agent-activity.sh` | Hook target — appends JSONL events (works without jq) |
| `scripts/agent-run-summary.sh` | Generates per-run markdown summaries in `development/agent-runs/` |
| `scripts/analyze-agent-metrics.sh` | CLI metrics report — events by tool, most-touched files, daily volume |

### Feedback Loop

`/review-changes` now captures user feedback on code review findings:
- Feedback is logged to the activity log for trend analysis
- `/analyze-agents` reads the log and suggests agent improvements
- Agent memory is updated based on feedback patterns

### Directory Structure

```
.claude/agent-memory/           # Git-committed, team-shared
├── code-reviewer/
│   ├── MEMORY.md               # Active memory (<100 lines)
│   └── old-memories/           # Archived entries (dated .md files)
├── test-runner/
│   ├── MEMORY.md
│   └── old-memories/
└── ... (16 agent directories)

.claude/agent-memory-local/     # Gitignored, machine-local
```

## Settings

### `settings.json` (shared, committed to git)
- Pattern-based permissions with wildcards: `Bash(pytest *)`, `Bash(docker exec *)`
- Deny rules for destructive operations
- Environment variables
- PostToolUse hooks: pipeline reminder + activity logging to JSONL

### `settings.local.json` (personal, gitignored)
- Additional permissions for your specific workflow
- Override model preferences
- Local environment variables

## Customization

Every template file contains `{{PLACEHOLDER}}` markers. The bootstrap skill replaces these automatically, but you can also edit them manually:

| Placeholder | Replace With |
|-------------|-------------|
| `{{PROJECT_NAME}}` | Your project name |
| `{{TECH_STACK}}` | e.g., "Python 3.12, FastAPI, PostgreSQL" |
| `{{PACKAGE_MANAGER}}` | e.g., "pip", "pnpm", "cargo" |
| `{{BUILD_COMMAND}}` | e.g., "pnpm build", "cargo build" |
| `{{TEST_COMMAND}}` | e.g., "pytest", "pnpm test", "cargo test" |
| `{{LINT_COMMAND}}` | e.g., "ruff check", "eslint .", "clippy" |
| `{{TYPE_CHECK_COMMAND}}` | e.g., "mypy src/", "tsc --noEmit" |
| `{{DEV_SERVER_COMMAND}}` | e.g., "uvicorn main:app --reload" |
| `{{FRAMEWORK}}` | e.g., "FastAPI", "Next.js", "Rails" |
| `{{DB_TYPE}}` | e.g., "PostgreSQL", "MongoDB", "SQLite" |
| `{{MIGRATION_TOOL}}` | e.g., "Alembic", "Prisma", "diesel" |

## Removing Agents You Don't Need

Not every project needs all 16 agents. Remove any `.claude/agents/*.md` file you don't need:

| If your project has no... | Remove these agents |
|---------------------------|-------------------|
| Database | `migration-helper.md` |
| Frontend | `frontend-developer.md`, `api-sync-checker.md` |
| Production deployment | `deploy-checker.md` |
| E2E testing | `e2e-tester.md` |
| ML/RL training | `ml-engineer.md` |
| Backend code | `backend-developer.md` |

**Minimum viable set:** `code-reviewer`, `test-runner`, `context-manager`, `planner`.

## Inspired By

This starter kit was extracted from the [AiTradingAgent](https://github.com/...) platform's production agentic layer — 66 CLAUDE.md files, 16 custom agents, 6 execution pipelines, and battle-tested conventions.
