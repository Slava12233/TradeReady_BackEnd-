---
task_id: 19
title: "Remove CLI --api-key arguments"
type: task
agent: "security-reviewer"
phase: 9
depends_on: []
status: "completed"
board: "[[agent-deployment-training/README]]"
priority: "high"
files: ["agent/strategies/rl/data_prep.py", "agent/strategies/rl/runner.py", "agent/strategies/rl/evaluate.py", "agent/strategies/rl/deploy.py", "agent/strategies/regime/validate.py", "agent/strategies/ensemble/optimize_weights.py", "agent/strategies/ensemble/validate.py", "agent/strategies/ensemble/run.py"]
tags:
  - task
  - deployment
  - training
---

# Task 19: Remove CLI --api-key arguments

## Assigned Agent: `security-reviewer`

## Objective
Remove `--api-key` CLI arguments from 8 scripts to prevent API key exposure in process lists (`ps aux`) and shell history (HIGH-3 from security review).

## Approach
All 8 scripts already have pydantic-settings config classes that read from `agent/.env`. Remove the `--api-key` argparse argument and rely solely on env var / `.env` file.

## Files to Modify
All 8 files listed above — remove `--api-key` argument from `argparse.ArgumentParser`, remove the override logic that applies CLI arg to config.

## Acceptance Criteria
- [ ] No `--api-key` argument in any CLI parser
- [ ] All scripts read API key from env var or `.env` file
- [ ] `--help` output no longer shows `--api-key`
- [ ] Scripts fail with clear error if API key not set in env
- [ ] All existing tests pass

## Dependencies
None — can start immediately.

## Agent Instructions
Read `development/code-reviews/security-review-agent-strategies.md` HIGH-3 for the full list. Each script has a `pydantic-settings` config class with an env prefix. The API key should be read from `PLATFORM_API_KEY` or the prefix-specific variant (e.g., `RL_PLATFORM_API_KEY`). Keep `--base-url` since that's not sensitive.

## Estimated Complexity
Low — removing arguments from 8 files.
