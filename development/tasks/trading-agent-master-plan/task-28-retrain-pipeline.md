---
task_id: 28
title: "Build automated retraining pipeline"
type: task
agent: "ml-engineer"
phase: 4
depends_on: [14, 23]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/retrain.py", "src/tasks/celery_app.py"]
tags:
  - task
  - ml
  - retraining
  - continuous-learning
---

# Task 28: Automated retraining pipeline

## Assigned Agent: `ml-engineer`

## Objective
Create `RetrainOrchestrator` that manages periodic retraining of all ML strategies with A/B testing before deployment.

## Schedule
| Component | Frequency |
|-----------|----------|
| Ensemble weights | Every trading session |
| Regime classifier | Weekly |
| Genome population | Weekly (2-3 new generations) |
| RL models (PPO) | Monthly (rolling 6-month window) |

## Retrain Process (for each component)
1. Train new model on recent + historical data
2. Backtest on held-out period
3. Compare to current model via `ABTestRunner`
4. Deploy only if new model outperforms
5. Log results to `agent_learnings`

## Files to Create/Modify
- `agent/strategies/retrain.py` — `RetrainOrchestrator` class
- `src/tasks/celery_app.py` — add beat tasks for each schedule

## Acceptance Criteria
- [ ] `RetrainOrchestrator` manages all 4 retraining schedules
- [ ] A/B comparison gates deployment (no blind deployment)
- [ ] Celery beat tasks registered for weekly/monthly schedules
- [ ] Retraining results logged to memory system
- [ ] Tests for orchestration logic

## Estimated Complexity
High — orchestrating multiple training pipelines with A/B testing.
