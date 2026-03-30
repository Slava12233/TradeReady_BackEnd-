---
task_id: R5-02
title: "Add 4 Celery beat schedule entries for retraining"
type: task
agent: "backend-developer"
phase: 4
depends_on: ["R5-01"]
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["src/tasks/celery_app.py"]
tags:
  - task
  - retraining
  - celery
  - scheduling
---

# Task R5-02: Add Celery Beat Schedule Entries

## Assigned Agent: `backend-developer`

## Objective
Add 4 Celery beat schedule entries for automated retraining on different cadences.

## Files to Modify/Create
- `src/tasks/celery_app.py` — add beat schedule entries

## Acceptance Criteria
- [ ] Ensemble weights: every 8 hours
- [ ] Regime classifier: weekly (Sunday 4:00 AM)
- [ ] Genome population: weekly (Wednesday 5:00 AM)
- [ ] RL models: monthly (1st of month, 3:00 AM)
- [ ] Schedules staggered to avoid concurrent CPU-intensive training
- [ ] `celery -A src.tasks.celery_app inspect scheduled` shows all 4 entries

## Dependencies
- R5-01 (task functions must exist)

## Estimated Complexity
Medium — schedule configuration with stagger logic
