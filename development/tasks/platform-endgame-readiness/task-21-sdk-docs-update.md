---
task_id: 21
title: "Update SDK README with examples and quickstart"
type: task
agent: "doc-updater"
phase: 3
depends_on: [20]
status: "done"
priority: "low"
board: "[[platform-endgame-readiness/README]]"
files:
  - "sdk/README.md"
tags:
  - task
  - documentation
  - sdk
  - phase-3
---

# Task 21: Update SDK README with examples and quickstart

## Assigned Agent: `doc-updater`

## Objective
Update the SDK README to document all new methods and link to the example scripts.

## Context
Task 20 creates 5 example scripts. This task updates the SDK docs to reference them and document new API methods added during this plan.

## Files to Modify/Create
- `sdk/README.md` — Add: examples section with descriptions, quickstart for each example, new methods reference (batch_step_fast, compute_deflated_sharpe, get_indicators, compare_strategies, webhook CRUD)

## Acceptance Criteria
- [x] SDK README has an "Examples" section listing all 5 examples with descriptions
- [x] Each example has a brief description of what it demonstrates
- [x] New SDK methods are documented in the README
- [x] Quickstart instructions (prerequisites, env vars, how to run)

## Dependencies
- **Task 20** must complete first (creates the examples)

## Agent Instructions
1. Read current `sdk/README.md` to understand existing structure
2. Read `sdk/CLAUDE.md` for SDK documentation patterns
3. Add the examples section without disrupting existing content
4. Keep descriptions concise — the example scripts themselves are well-commented

## Estimated Complexity
Low — documentation update following existing patterns.
