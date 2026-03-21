---
task_id: 05
title: "Create & seed MEMORY.md for development agents"
type: task
agent: "context-manager"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "medium"
files:
  - ".claude/agent-memory/backend-developer/MEMORY.md"
  - ".claude/agent-memory/frontend-developer/MEMORY.md"
  - ".claude/agent-memory/ml-engineer/MEMORY.md"
  - ".claude/agent-memory/e2e-tester/MEMORY.md"
tags:
  - task
  - agent
  - memory
---

# Task 05: Create & seed MEMORY.md for development agents

## Assigned Agent: `context-manager`

## Objective
Create seeded MEMORY.md files for 4 development agents: `backend-developer`, `frontend-developer`, `ml-engineer`, `e2e-tester`.

## Context
Phase 1 of Agent Memory Strategy. Development agents write code and benefit from knowing project conventions, past patterns, and common pitfalls.

## Files to Create
- `.claude/agent-memory/backend-developer/MEMORY.md` — seed with:
  - Dependency injection pattern (`src/dependencies.py` — typed aliases)
  - Repository pattern (all DB access through repos)
  - Exception hierarchy (`TradingPlatformError` → subclasses)
  - Import order enforcement (stdlib → third-party → local)
  - Decimal for money, never float
  - Agent-scoped operations (agent_id on all trading tables)

- `.claude/agent-memory/frontend-developer/MEMORY.md` — seed with:
  - Next.js 16 / React 19 / Tailwind v4 stack
  - shadcn/ui component library (59 primitives)
  - TanStack Query patterns (from `Frontend/src/hooks/CLAUDE.md`)
  - Zustand stores (6 stores, from `Frontend/src/stores/CLAUDE.md`)
  - API client patterns (`Frontend/src/lib/api-client.ts`)
  - Performance patterns applied (memo, lazy loading, PriceBatchBuffer)

- `.claude/agent-memory/ml-engineer/MEMORY.md` — seed with:
  - 5 strategy system (PPO RL, genetic, regime, risk, ensemble)
  - tradeready-gym environments (7 envs, 4 rewards, 3 wrappers)
  - SB3 integration patterns
  - Training pipeline structure (`agent/strategies/`)

- `.claude/agent-memory/e2e-tester/MEMORY.md` — seed with:
  - Platform access points (API :8000, Frontend :3000, WS)
  - Account creation flow
  - Agent creation + API key generation flow
  - Backtest lifecycle (create → start → step → results)
  - Battle lifecycle (draft → pending → active → completed)

## Acceptance Criteria
- [ ] 4 MEMORY.md files created
- [ ] Each reflects actual project conventions (not generic advice)
- [ ] Each file <100 lines

## Estimated Complexity
Medium — requires reading module CLAUDE.md files to extract conventions.
