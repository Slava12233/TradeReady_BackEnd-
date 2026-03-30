---
task_id: R5-01
title: "Create Celery task wrapping RetrainOrchestrator"
type: task
agent: "backend-developer"
phase: 4
depends_on: ["R3-01"]
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["src/tasks/retrain_tasks.py", "src/tasks/celery_app.py"]
tags:
  - task
  - retraining
  - celery
  - ml
---

# Task R5-01: Create Celery Task Wrapping RetrainOrchestrator

## Assigned Agent: `backend-developer`

## Objective
Create a Celery task that bridges the sync Celery boundary to the async `RetrainOrchestrator.run_scheduled_cycle()`.

## Context
The `RetrainOrchestrator` and `DriftDetector` code exists (Tasks 28/31 of master plan) but is not connected to the Celery beat schedule. This task creates the bridge.

## Files to Modify/Create
- `src/tasks/retrain_tasks.py` (new) — Celery tasks for each retraining type
- `src/tasks/celery_app.py` — register new task module in `include` list

## Acceptance Criteria
- [x] `run_retraining_cycle` Celery task wraps `RetrainOrchestrator`
- [x] Individual tasks: `retrain_ensemble`, `retrain_regime`, `retrain_genome`, `retrain_rl`
- [x] `soft_time_limit=3600`, `time_limit=3900` (1 hour + 5 min hard limit)
- [x] Lazy imports inside task functions (circular import avoidance)
- [x] `asyncio.run()` bridge pattern for async orchestrator
- [x] Task module registered in `celery_app.py` include list
- [ ] `run_retraining_cycle.delay()` executes successfully (requires running worker)

## Dependencies
- R3-01 (at least one trained model must exist for meaningful execution)

## Agent Instructions
1. Read `src/tasks/CLAUDE.md` for Celery task patterns and conventions
2. Use `asyncio.run()` to bridge sync Celery → async orchestrator
3. Consider separate Celery queue: `@app.task(queue="ml_training")`
4. Return JSON summary with per-strategy results

## Estimated Complexity
Medium — async bridge pattern + task registration
