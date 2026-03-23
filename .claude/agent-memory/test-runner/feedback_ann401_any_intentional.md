---
name: ANN401 Any annotations in ML strategy files are intentional
description: ANN401 lint errors using typing.Any in agent/strategies/rl/train.py and ensemble/run.py are pre-existing and intentional — do not treat as regressions
type: feedback
---

ANN401 (Dynamically typed expressions disallowed) errors in `agent/strategies/rl/train.py` and `agent/strategies/ensemble/run.py` are intentional and pre-existing.

**Why:** These files use `Any` for function parameters and return types because they accept/return objects from optional ML dependencies (stable-baselines3, torch, xgboost) that may not be installed. Specifying concrete types would require importing the optional packages at module level, breaking the lazy-import pattern used to make ML libraries optional.

**How to apply:** When running ruff on these files, ANN401 errors should be noted as pre-existing but not flagged as new regressions introduced by recent changes. Only F8xx (undefined name/import) errors in these files should be treated as real bugs.
