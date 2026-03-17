# Agentic Layer — CLAUDE.md Distribution Plan

## Goal

Create a self-maintaining knowledge layer across the entire codebase so that Claude Code agents can understand any part of the project without loading the full context. Each folder gets a `CLAUDE.md` file describing its purpose, key files, patterns, gotchas, and recent changes. The root `CLAUDE.md` becomes an index that references all sub-files.

## Design Principles

1. **Minimal context, maximum understanding** — Each CLAUDE.md should give an agent enough info to work in that folder without reading the root CLAUDE.md
2. **Self-maintaining** — Root CLAUDE.md includes a rule requiring agents to update the relevant CLAUDE.md when they modify code in that folder
3. **No duplication** — Sub-CLAUDE.md files contain folder-specific details; root CLAUDE.md contains cross-cutting concerns (architecture, commands, env vars)
4. **Evolves with code** — Each file has a "Last Updated" timestamp and "Recent Changes" section

---

## Phase 1: Backend `src/` modules (15 files)

Each file follows a standard template (see below). These are the highest-value targets since backend is the core.

### Tasks

| # | File Path | Description | Priority | Status |
|---|-----------|-------------|----------|--------|
| 1.1 | `src/accounts/CLAUDE.md` | Account service, registration, auth, API keys | High | DONE |
| 1.2 | `src/agents/CLAUDE.md` | Multi-agent CRUD, clone, reset, avatar generation | High | DONE |
| 1.3 | `src/api/CLAUDE.md` | API gateway overview, middleware stack, route registry | High | DONE |
| 1.4 | `src/api/routes/CLAUDE.md` | All REST endpoints, auth requirements, patterns | High | DONE |
| 1.5 | `src/api/schemas/CLAUDE.md` | Pydantic v2 schemas, validation patterns | Medium | DONE |
| 1.6 | `src/api/middleware/CLAUDE.md` | Auth, rate limiting, logging middleware — execution order | High | DONE |
| 1.7 | `src/api/websocket/CLAUDE.md` | WebSocket channels, protocol, subscription model | Medium | DONE |
| 1.8 | `src/backtesting/CLAUDE.md` | Backtest engine, sandbox, time simulation, data replay | High | DONE |
| 1.9 | `src/battles/CLAUDE.md` | Battle system, ranking, snapshots, historical engine | High | DONE |
| 1.10 | `src/cache/CLAUDE.md` | Redis cache layer, key patterns, pub/sub | Medium | DONE |
| 1.11 | `src/database/CLAUDE.md` | Models, session management, repository pattern | High | DONE |
| 1.12 | `src/database/repositories/CLAUDE.md` | All repository classes, query patterns | High | DONE |
| 1.13 | `src/mcp/CLAUDE.md` | MCP server, tools, stdio transport | Medium | DONE |
| 1.14 | `src/metrics/CLAUDE.md` | Unified metrics calculator, adapters | Medium | DONE |
| 1.15 | `src/monitoring/CLAUDE.md` | Prometheus metrics, health checks | Low | DONE |
| 1.16 | `src/order_engine/CLAUDE.md` | Order execution, matching, slippage | High | DONE |
| 1.17 | `src/portfolio/CLAUDE.md` | Portfolio tracking, PnL calculation | Medium | DONE |
| 1.18 | `src/price_ingestion/CLAUDE.md` | Binance WS, tick buffering, flush cycle | High | DONE |
| 1.19 | `src/risk/CLAUDE.md` | Risk manager, circuit breaker, position limits | Medium | DONE |
| 1.20 | `src/tasks/CLAUDE.md` | Celery tasks, beat schedule, cleanup jobs | Medium | DONE |
| 1.21 | `src/utils/CLAUDE.md` | Exceptions hierarchy, shared utilities | Low | DONE |

**Estimated effort:** ~2 hours (read each module, generate CLAUDE.md)

---

## Phase 2: Tests (2 files)

| # | File Path | Description | Priority | Status |
|---|-----------|-------------|----------|--------|
| 2.1 | `tests/CLAUDE.md` | Test philosophy, conftest fixtures, async patterns, gotchas | High | DONE |
| 2.2 | `tests/unit/CLAUDE.md` | Unit test inventory, mock patterns | Medium | DONE |
| 2.3 | `tests/integration/CLAUDE.md` | Integration test setup, app factory, Docker deps | Medium | DONE |

---

## Phase 3: Database Migrations (1 file)

| # | File Path | Description | Priority | Status |
|---|-----------|-------------|----------|--------|
| 3.1 | `alembic/CLAUDE.md` | Migration workflow, async env, naming convention, current head | Medium | DONE |

---

## Phase 4: Frontend (6 files)

*Note: Frontend already has `Frontend/CLAUDE.md`. We add sub-files for key areas.*

| # | File Path | Description | Priority | Status |
|---|-----------|-------------|----------|--------|
| 4.1 | `Frontend/src/components/CLAUDE.md` | Component organization, shared vs feature, shadcn/ui patterns | Medium | DONE |
| 4.2 | `Frontend/src/hooks/CLAUDE.md` | Hook inventory, TanStack Query patterns, WebSocket hooks | Medium | DONE |
| 4.3 | `Frontend/src/stores/CLAUDE.md` | Zustand stores, persistence, agent/battle state | Medium | DONE |
| 4.4 | `Frontend/src/app/CLAUDE.md` | App Router structure, layouts, auth vs dashboard groups | Medium | DONE |
| 4.5 | `Frontend/src/lib/CLAUDE.md` | API client, utilities, constants | Low | DONE |
| 4.6 | `Frontend/src/components/backtest/CLAUDE.md` | Backtest UI components, sub-folder structure | Low | DONE |
| 4.7 | `Frontend/src/components/battles/CLAUDE.md` | Battle UI components, live dashboard, replay | Low | DONE |

---

## Phase 5: SDK, Scripts, Docs (3 files)

| # | File Path | Description | Priority | Status |
|---|-----------|-------------|----------|--------|
| 5.1 | `sdk/CLAUDE.md` | SDK architecture, sync/async clients, WS client | Low | DONE |
| 5.2 | `scripts/CLAUDE.md` | Available scripts, when to run each, dependencies | Low | DONE |
| 5.3 | `docs/CLAUDE.md` | Documentation inventory, audience for each doc | Low | DONE |

---

## Phase 6: Root CLAUDE.md Refactor

| # | Task | Description | Priority | Status |
|---|------|-------------|----------|--------|
| 6.1 | Add sub-file index | Add a "## CLAUDE.md Index" section listing all sub-files with one-line descriptions | High | DONE |
| 6.2 | Add self-maintenance rule | Add rule: "When modifying code in any folder, update that folder's CLAUDE.md if behavior, files, or patterns changed" | High | DONE |
| 6.3 | Trim redundancy | Move folder-specific details from root to sub-files, keep root as architecture overview + cross-cutting rules | Medium | DONE |
| 6.4 | Add last-updated tracking | Each sub-CLAUDE.md gets a `<!-- last-updated: YYYY-MM-DD -->` comment | Low | DONE |

---

## Phase 7: .claude Sub-Agents (Future)

*Deferred to after Phase 1-6 are complete.*

| # | Task | Description | Priority |
|---|------|-------------|----------|
| 7.1 | Create `.claude/agents/code-reviewer.md` | Agent that reviews PRs using CLAUDE.md context | Future |
| 7.2 | Create `.claude/agents/test-writer.md` | Agent that writes tests for modified code | Future |
| 7.3 | Create `.claude/agents/doc-updater.md` | Agent that updates CLAUDE.md files after code changes | Future |
| 7.4 | Create `.claude/agents/migration-helper.md` | Agent specialized in Alembic migrations | Future |

---

## CLAUDE.md Template

Every sub-CLAUDE.md follows this structure:

```markdown
# {Module Name}

<!-- last-updated: YYYY-MM-DD -->

> One-line purpose of this module.

## What This Module Does

2-3 sentence overview of the module's responsibility.

## Key Files

| File | Purpose |
|------|---------|
| `file.py` | What it does |

## Architecture & Patterns

- Key patterns used (repository, factory, singleton, etc.)
- Important abstractions
- Dependency direction

## Public API / Interfaces

Key classes, functions, or endpoints exposed by this module.

## Dependencies

- What this module depends on (other src/ modules, external packages)
- What depends on this module

## Common Tasks

### Adding a new X
Step-by-step for the most common modification.

### Modifying Y
Step-by-step for another common task.

## Gotchas & Pitfalls

- Non-obvious things that will bite you
- Edge cases
- Things that look wrong but are intentional

## Recent Changes

- `YYYY-MM-DD` — Brief description of what changed
```

---

## Execution Order

```
Phase 1 (backend src/) ──→ Phase 6.1-6.2 (root update) ──→ Phase 2 (tests)
     │                                                           │
     └── can start immediately                                   ▼
                                                          Phase 3 (alembic)
                                                               │
                                                               ▼
                                                          Phase 4 (frontend)
                                                               │
                                                               ▼
                                                          Phase 5 (sdk/scripts/docs)
                                                               │
                                                               ▼
                                                          Phase 6.3-6.4 (cleanup)
                                                               │
                                                               ▼
                                                          Phase 7 (sub-agents, future)
```

**Phase 1 + Phase 6.1-6.2 are the MVP.** Everything else builds on top.

---

## Success Criteria

1. Every `src/` module has a CLAUDE.md that lets an agent understand the module without reading all source files
2. Root CLAUDE.md has an index pointing to all sub-files
3. Root CLAUDE.md has a self-maintenance rule
4. An agent dropped into any folder can read the local CLAUDE.md and start working effectively
5. No significant duplication between root and sub-files

---

## Total File Count

| Phase | Files | Status |
|-------|-------|--------|
| Phase 1: Backend | 21 | DONE |
| Phase 2: Tests | 3 | DONE |
| Phase 3: Alembic | 1 | DONE |
| Phase 4: Frontend | 7 | DONE |
| Phase 5: SDK/Scripts/Docs | 3 | DONE |
| Phase 6: Root refactor | 1 (edit) | DONE |
| **Total** | **36 new + 1 edit** | |
