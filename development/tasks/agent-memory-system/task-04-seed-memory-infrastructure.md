---
task_id: 04
title: "Create & seed MEMORY.md for infrastructure agents"
type: task
agent: "context-manager"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "medium"
files:
  - ".claude/agent-memory/deploy-checker/MEMORY.md"
  - ".claude/agent-memory/api-sync-checker/MEMORY.md"
  - ".claude/agent-memory/doc-updater/MEMORY.md"
  - ".claude/agent-memory/migration-helper/MEMORY.md"
  - ".claude/agent-memory/perf-checker/MEMORY.md"
tags:
  - task
  - agent
  - memory
---

# Task 04: Create & seed MEMORY.md for infrastructure agents

## Assigned Agent: `context-manager`

## Objective
Create seeded MEMORY.md files for 5 infrastructure agents: `deploy-checker`, `api-sync-checker`, `doc-updater`, `migration-helper`, `perf-checker`.

## Context
Phase 1 of Agent Memory Strategy. Infrastructure agents handle cross-cutting concerns and benefit from knowing the project's infrastructure patterns.

## Files to Create
- `.claude/agent-memory/deploy-checker/MEMORY.md` — seed with:
  - Docker compose services and profiles (agent profile is opt-in)
  - CI/CD pipeline structure (GitHub Actions)
  - Environment variables that are required vs optional
  - Known deployment gotchas

- `.claude/agent-memory/api-sync-checker/MEMORY.md` — seed with:
  - Frontend API client location (`Frontend/src/lib/api-client.ts`)
  - Backend schema locations (`src/api/schemas/`)
  - WebSocket message shapes (`src/api/websocket/`)
  - Known type mismatches found and fixed

- `.claude/agent-memory/doc-updater/MEMORY.md` — seed with:
  - Documentation file inventory (`docs/`)
  - SDK docs location (`sdk/`)
  - CLAUDE.md update patterns
  - API reference generation patterns

- `.claude/agent-memory/migration-helper/MEMORY.md` — seed with:
  - Current migration head: 017
  - TimescaleDB hypertable rules (PKs must include time column)
  - Two-phase NOT NULL pattern
  - Existing models inventory (17 models)

- `.claude/agent-memory/perf-checker/MEMORY.md` — seed with:
  - Performance fixes applied (from `development/code-reviews/perf-check-agent-strategies.md`)
  - 8 HIGH perf fixes from agent deployment (asyncio.gather, deque caps, etc.)
  - Known hot paths (price ingestion, order execution, WebSocket broadcast)
  - Frontend perf patterns (memo, lazy loading, virtual scrolling)

## Acceptance Criteria
- [ ] 5 MEMORY.md files created
- [ ] Each seeded with project-specific patterns
- [ ] Each file <100 lines

## Estimated Complexity
Medium — 5 files, each requiring targeted research.
