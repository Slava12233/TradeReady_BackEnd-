# Planner Agent Memory

<!-- last-updated: 2026-04-08 -->

## Task Board Patterns

### Observed Plan Sizes
- `tradeready-test-agent/` — 18 tasks (single workflow package, moderate scope)
- `agent-strategies/` — 29 tasks (5 strategy phases: PPO/genetic/regime/risk/ensemble)
- `agent-deployment-training/` — 23 tasks (infra + ML pipeline + security/perf fixes)
- `agent-ecosystem/` — 36 tasks (2 phases: DB+conversation+memory / permissions+trading)
- `frontend-performance-fixes/` — 23 tasks (3 optimization phases)
- **Sweet spot: 18-36 tasks per board. >36 signals scope creep; split into phases.**

### Task File Structure (YAML frontmatter)
```
task_id, title, agent, phase, depends_on, status, priority, files
```
- `status`: `pending` → `in_progress` → `completed` / `failed`
- `depends_on`: list of task IDs — drives parallel execution grouping
- Always include a `run-tasks.md` with parallel execution groups (Group A/B/C)
- Always include a `README.md` with phase overview and success criteria

### Phase Structure Pattern
- Phase 1: Data layer (DB models + migration + repositories)
- Phase 2: Business logic (services, engines, core algorithms)
- Phase 3: API / integration layer (routes, schemas, tools)
- Phase 4: Quality gate (tests, code review, security, perf, context update)
- Last 2-3 tasks are always: test-runner → doc-updater → context-manager

---

## Mandatory Post-Change Pipeline (never skip)
```
code-reviewer → test-runner → context-manager
```
API/schema changes add: `api-sync-checker → doc-updater` before the above.
Security-sensitive changes add: `security-reviewer (fix) → security-auditor (verify)` before code-reviewer.

---

## Architectural Constraints (from root CLAUDE.md)

### Dependency Direction (strict — never violate)
```
Routes → Schemas + Services → Repositories + Cache → Models + Session
```

### Middleware Execution Order (LIFO registration)
```
RateLimitMiddleware → AuthMiddleware → LoggingMiddleware → route handler
```
AuthMiddleware must run before RateLimitMiddleware so `request.state.account` is populated.

### Agent Scoping Rules
- All trading tables (`balances`, `orders`, `trades`, `positions`) keyed by `agent_id`
- API key auth: tries agents table first, falls back to accounts table
- JWT auth: account from JWT, agent context via `X-Agent-Id` header
- CircuitBreaker is account-scoped — never a singleton

### Database Rules
- `NUMERIC(20,8)` for all price/quantity/balance columns (never `float`)
- TimescaleDB hypertables only for time-series: `ticks`, `portfolio_snapshots`, `backtest_snapshots`
- All write operations must be atomic (SQLAlchemy transactions)

---

## Risk Patterns to Always Include in Plans

### Migration Safety
- Two-phase NOT NULL: add nullable → backfill → add constraint
- No destructive ALTER without rollback path
- Hypertable PK rules differ — delegate to `migration-helper` agent before any migration task

### API Compatibility
- Schema changes need `api-sync-checker` run — Pydantic vs TypeScript types diverge silently
- WebSocket message shape changes break all connected clients immediately
- New required fields on existing endpoints = breaking change (version or make optional)

### Agent Isolation
- Never share mutable state between agents (each has own wallet, risk profile, API key)
- Budget limits and capability gates must be enforced at PermissionEnforcer level, not just API
- Security review required for any new capability or role assignment path

### Performance Red Flags
- N+1 queries on agent listing endpoints (eagerly load related counts)
- Blocking sync calls in async routes (use `asyncio.to_thread`)
- Unbounded in-memory structures (deque with maxlen, not plain list)
- React: missing memo on table rows that receive price updates (re-render storm)

---

## Completed Plan Inventory

See [reference_completed_plans.md](reference_completed_plans.md) for full listing (7 boards complete, 177 total tasks, 1 plan pending).
Sweet spot: 18-36 tasks per board. Over 36 signals scope creep; split into phases.

---

## CI/CD Deploy Flow (from `.github/workflows/deploy.yml`)

1. Push to `main` triggers test → deploy pipeline
2. SSH into server, record rollback commit + migration revision
3. `pg_dump` backup (excludes hypertable data), `git reset --hard origin/main`
4. `docker compose build api ingestion celery`, infrastructure health check
5. `alembic upgrade head`, rolling restart (celery-beat → celery → api → ingestion)
6. Health check curl; auto-rollback on failure (git checkout + alembic downgrade)

Key: deploy is fully automated on push to `main`. No manual intervention needed.

---

## Recommendation Plan Pattern (learned 2026-04-08)

For C-level recommendation execution plans, use this structure per recommendation:
- Objective (success criteria), Prerequisites (checkboxes), Steps (numbered with commands/file paths)
- Verification checklist, Estimated effort, Agent assignment, Dependencies, Risk table
- Include: execution timeline (Gantt-style), dependency graph, quick wins section, summary table
- Recommendations that can run in parallel should be grouped (Group A/B/C pattern from task boards)
