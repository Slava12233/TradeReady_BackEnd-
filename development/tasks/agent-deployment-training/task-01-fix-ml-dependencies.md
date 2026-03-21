---
task_id: 01
title: "Add ML optional dependencies to agent/pyproject.toml"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "completed"
board: "[[agent-deployment-training/README]]"
priority: "high"
files: ["agent/pyproject.toml", "agent/strategies/__init__.py"]
tags:
  - task
  - deployment
  - training
---

# Task 01: Add ML optional dependencies to agent/pyproject.toml

## Assigned Agent: `backend-developer`

## Objective
The strategy code (`agent/strategies/`) imports `stable-baselines3`, `torch`, `xgboost`, `scikit-learn`, `joblib`, `numpy`, and `pandas` — but none of these are declared in `agent/pyproject.toml`. Add them as optional dependency groups so `pip install -e "agent/[ml]"` installs everything needed.

## Context
All 29 strategy tasks are code-complete, but the packages can't actually be imported because the ML dependencies aren't declared. This is the first blocker to running anything.

## Files to Modify
- `agent/pyproject.toml` — add `[project.optional-dependencies]` groups: `ml`, `all`
- Add `tradeready-gym` as a core dependency (local package)

## Changes Required

Add to `agent/pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
]
ml = [
    "stable-baselines3[extra]>=2.3",
    "torch>=2.2",
    "xgboost>=2.0",
    "scikit-learn>=1.4",
    "joblib>=1.3",
    "numpy>=1.26",
    "pandas>=2.2",
    "tradeready-gym",
]
all = [
    "tradeready-test-agent[dev,ml]",
]
```

## Acceptance Criteria
- [ ] `pip install -e sdk/` succeeds
- [ ] `pip install -e tradeready-gym/` succeeds
- [ ] `pip install -e "agent/[all]"` succeeds and installs all ML packages
- [ ] `python -c "from stable_baselines3 import PPO"` works
- [ ] `python -c "import torch; print(torch.__version__)"` works
- [ ] `python -c "from agent.strategies.rl.config import RLConfig"` works
- [ ] `python -c "from agent.strategies.regime.classifier import RegimeClassifier"` works
- [ ] `python -c "from agent.strategies.ensemble.meta_learner import MetaLearner"` works

## Dependencies
None — this is the first task.

## Agent Instructions
Read `agent/pyproject.toml` first. Keep the existing `dev` group. Add `ml` and `all` groups. The `tradeready-gym` package is local — it must be installed with `pip install -e tradeready-gym/` before the agent package. Add it to `ml` deps so it's declared, but note users must install it editable first.

## Estimated Complexity
Low — editing one TOML file and verifying imports.
