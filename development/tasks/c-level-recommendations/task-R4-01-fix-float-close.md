---
task_id: R4-01
title: "Fix float(c.close) in server_handlers.py"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "medium"
board: "[[c-level-recommendations/README]]"
files: ["agent/server_handlers.py"]
tags:
  - task
  - code-quality
  - financial-precision
---

# Task R4-01: Fix `float(c.close)` in `server_handlers.py`

## Assigned Agent: `backend-developer`

## Objective
Replace `float(c.close)` with `Decimal` arithmetic in the SMA calculation in `handle_analyze()`.

## Context
Line 210: `closes = [float(c.close) for c in candles]` violates the project-wide Decimal convention for financial values. Identified in Phase 0 Group A code review (2026-03-22).

## Files to Modify/Create
- `agent/server_handlers.py:210` — replace float cast with Decimal

## Acceptance Criteria
- [x] `float(c.close)` replaced with `Decimal` conversion
- [x] SMA calculation uses `Decimal` division
- [x] No `float()` calls on financial values in this file
- [x] Existing tests pass

## Dependencies
None

## Estimated Complexity
Low — single line fix with Decimal arithmetic
