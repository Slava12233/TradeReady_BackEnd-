---
paths:
  - ".claude/agents/**/*.md"
  - "src/**/*.py"
  - "Frontend/**/*.{ts,tsx}"
  - "agent/**/*.py"
  - "tests/**/*.py"
---

# Sub-Agents & Pipelines

16 specialized agents in `.claude/agents/`. All have `memory: project` enabled — see `.claude/agent-memory/`.

## Agent Inventory

### Quality Gate Agents (run after every change)

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| `code-reviewer` | Reviews code against project standards. Saves reports to `development/code-reviews/` | **After every code change** (step 1) |
| `test-runner` | Maps changed files → tests, runs them, writes missing tests | **After every code change** (step 2) |
| `context-manager` | Maintains `development/context.md` and syncs CLAUDE.md files | **After every task** (mandatory final step) |

### Security Agents

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| `security-auditor` | Read-only audit for auth bypasses, injection, secrets, XSS | After security-sensitive changes |
| `security-reviewer` | Vulnerability detection AND remediation (can fix CRITICALs) | **PROACTIVELY** after auth/input/API code |

### Infrastructure Agents

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| `migration-helper` | Validates/generates Alembic migrations safely | **Before** any migration |
| `api-sync-checker` | Pydantic vs TypeScript type sync, route matching | After API/schema/frontend API changes |
| `deploy-checker` | Full deployment readiness (lint, types, tests, Docker, CI/CD) | Before production deploy or merge to `main` |
| `doc-updater` | Syncs docs with actual code | After API/schema/module changes |
| `perf-checker` | N+1 queries, blocking async, missing indexes, React renders | After DB/async/caching/hot path changes |

### Development Agents

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| `backend-developer` | Production async Python 3.12+ modules | New Python packages, business logic |
| `frontend-developer` | Next.js 16 / React 19 / Tailwind v4 features | Frontend features, components, pages |
| `ml-engineer` | RL pipelines, genetic algorithms, regime classifiers | Gymnasium RL, evolutionary optimization, ML |
| `e2e-tester` | Live E2E scenarios against running platform | Populate data, validate full stack, demo |

### Research & Planning Agents

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| `planner` | Detailed implementation plans (uses opus) | **PROACTIVELY** for features, refactoring |
| `codebase-researcher` | Investigate codebase, trace data flows | Before making changes |

## Agent Pipelines

### Standard Post-Change Pipeline (every code change)
```
code-reviewer → test-runner → context-manager
```

### API/Schema Change Pipeline
```
[changes] → api-sync-checker → doc-updater → code-reviewer → test-runner → context-manager
```

### Security-Sensitive Change Pipeline
```
[changes] → security-reviewer → security-auditor → code-reviewer → test-runner → context-manager
```

### Performance-Sensitive Change Pipeline
```
[changes] → perf-checker → code-reviewer → test-runner → context-manager
```

### Database Migration Pipeline
```
migration-helper → [apply migration] → deploy-checker → context-manager
```

### Feature Implementation Pipeline
```
planner → codebase-researcher → backend/frontend/ml-engineer → code-reviewer → test-runner → context-manager
```

## Mandatory Agent Rules

1. **After ANY code change**, run: `code-reviewer` → `test-runner` → `context-manager`. Never skip.
2. **Before ANY migration**, delegate to `migration-helper`.
3. **After API/schema changes**, run `api-sync-checker` then `doc-updater` before standard pipeline.
4. **Security-sensitive changes** (auth, middleware, agent scoping) → security pipeline.
5. **Performance-sensitive changes** (DB queries, async, caching) → `perf-checker` first.
6. If `test-runner` finds missing coverage, it writes new tests per `tests/CLAUDE.md`.
7. If tests fail, fix and re-run until all pass.
8. **`context-manager` is ALWAYS the final step.** Updates `development/context.md`, syncs CLAUDE.md files, appends to daily note.
9. **Always include Agent Activity Report** in final response:

```
## Agent Activity Report
| Agent | Task | Result |
|-------|------|--------|
| `agent-name` | What it did | Outcome |
**Pipeline:** agent1 → agent2 → agent3
**Total agents used:** N
```

## Agent Configuration Reference

Frontmatter fields: `name` (required), `description` (required), `tools` (required), `model` (optional: sonnet/opus/haiku).

Advanced: `memory` (project/user/local), `effort` (low-max), `isolation` (worktree), `maxTurns`, `hooks` (PreToolUse/PostToolUse/Stop).
