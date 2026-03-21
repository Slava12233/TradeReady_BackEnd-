---
task_id: 06
title: "Create & seed MEMORY.md for research & planning agents"
type: task
agent: "context-manager"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "medium"
files:
  - ".claude/agent-memory/planner/MEMORY.md"
  - ".claude/agent-memory/codebase-researcher/MEMORY.md"
tags:
  - task
  - agent
  - memory
---

# Task 06: Create & seed MEMORY.md for research & planning agents

## Assigned Agent: `context-manager`

## Objective
Create seeded MEMORY.md files for 2 research/planning agents: `planner` and `codebase-researcher`. `planner` already has `memory: project` in frontmatter.

## Context
Phase 1 of Agent Memory Strategy. These agents investigate and plan — they benefit from knowing past decisions, architectural patterns, and where to find things.

## Files to Create
- `.claude/agent-memory/planner/MEMORY.md` — seed with:
  - Past plan structures (phase-based, task-based)
  - Successful task board patterns (from `development/tasks/`)
  - Architectural decisions (dependency direction, agent scoping, middleware order)
  - Risk patterns to always consider (migration safety, API compatibility, agent isolation)
  - Task sizing patterns (from completed task boards: 23-36 tasks per plan)

- `.claude/agent-memory/codebase-researcher/MEMORY.md` — seed with:
  - CLAUDE.md hierarchy as navigation system (66 files)
  - Key entry points for common investigations:
    - Auth flow: `src/api/middleware/` → `src/accounts/` → `src/agents/`
    - Price flow: `src/price_ingestion/` → `src/cache/` → `src/database/`
    - Order flow: `src/api/routes/` → `src/risk/` → `src/order_engine/`
    - Agent flow: `src/agents/` → `agent/` → `agent/strategies/`
  - Test locations (`tests/unit/`, `tests/integration/`, `agent/tests/`)
  - Frontend structure (`Frontend/src/components/` — 130+ files, 23 hooks)

## Acceptance Criteria
- [ ] 2 MEMORY.md files created
- [ ] Planner memory references actual past plans and their sizes
- [ ] Researcher memory provides actionable navigation shortcuts
- [ ] Each file <100 lines

## Estimated Complexity
Medium — requires understanding project architecture to provide useful navigation.
