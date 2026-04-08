---
task_id: 15
title: "Create Getting Started guide for external agent developers"
type: task
agent: "doc-updater"
phase: 2
depends_on: [3]
status: "pending"
priority: "medium"
board: "[[recommendations-execution/README]]"
files:
  - "docs/getting-started-agents.md"
  - "sdk/examples/getting_started.py"
  - "docs/architecture-overview.md"
tags:
  - task
  - documentation
  - onboarding
---

# Task 15: Getting Started Guide for External Agent Developers

## Assigned Agent: `doc-updater`

## Objective
Create a comprehensive 9-step getting started guide that takes a Python developer from zero to a working agent in 30 minutes.

## Context
R5 from the C-level report. The plan at `development/recommendations-execution-plan.md` Section R5 has the full structure.

## Files to Modify/Create
- `docs/getting-started-agents.md` — 9-step guide (platform setup → price watcher → trade → backtest → RL → webhooks → DSR)
- `sdk/examples/getting_started.py` — Companion script validating steps 4-6
- `docs/architecture-overview.md` — High-level architecture for external developers

## Acceptance Criteria
- [ ] Guide covers all 9 steps from the plan
- [ ] Each step has working code snippets
- [ ] No assumed crypto/blockchain knowledge
- [ ] Companion script runs against live platform
- [ ] Architecture overview explains: what, how agents connect, data, operations, isolation, auth
- [ ] Links to SDK README, API reference, framework guides
- [ ] `ruff check` passes on companion script

## Dependencies
- **Task 3** (deploy complete — need live platform to validate code snippets)

## Agent Instructions
1. Read `development/recommendations-execution-plan.md` Section R5 for full structure
2. Read `sdk/README.md`, `docs/quickstart.md`, `docs/api_reference.md` for existing patterns
3. Test every code snippet mentally against the SDK methods
4. Target audience: "Python developer who has never used the platform"

## Estimated Complexity
High — comprehensive onboarding documentation with code snippets.
