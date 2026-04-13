---
task_id: B-08
title: "Save model artifact"
type: task
agent: "ml-engineer"
track: B
depends_on: ["B-07"]
status: "pending"
priority: "medium"
board: "[[april-2026-execution/README]]"
files: ["models/ppo_btc_v1.zip"]
tags:
  - task
  - ml
  - artifact
---

# Task B-08: Save model artifact

## Assigned Agent: `ml-engineer`

## Objective
Verify the model artifact exists, record its size and SHA-256 checksum for reproducibility tracking.

## Acceptance Criteria
- [ ] `models/ppo_btc_v1.zip` exists
- [ ] File size recorded
- [ ] SHA-256 checksum computed and recorded
- [ ] Model can be loaded successfully: `PPO.load("models/ppo_btc_v1.zip")`
- [ ] `models/` directory is in `.gitignore` (models should not be committed to git)

## Dependencies
- **B-07**: DSR validation complete (model is finalized)

## Agent Instructions
```bash
ls -la models/ppo_btc_v1.zip
sha256sum models/ppo_btc_v1.zip
```
Then verify the model loads:
```python
from stable_baselines3 import PPO
model = PPO.load("models/ppo_btc_v1.zip")
print(f"Model loaded. Policy: {model.policy}")
```
Ensure `models/` is in `.gitignore`. If not, add it.

## Estimated Complexity
Low — file verification.
