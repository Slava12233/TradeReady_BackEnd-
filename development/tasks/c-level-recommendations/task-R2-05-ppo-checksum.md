---
task_id: R2-05
title: "SHA-256 checksum verification before PPO.load()"
type: task
agent: "security-reviewer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["agent/strategies/rl/runner.py", "agent/strategies/rl/deploy.py", "agent/strategies/rl/evaluate.py", "agent/strategies/ensemble/run.py", "agent/strategies/checksum.py"]
tags:
  - task
  - security
  - ml
  - deserialization
---

# Task R2-05: SHA-256 Checksum Verification Before `PPO.load()`

## Assigned Agent: `security-reviewer`

## Objective
Enforce SHA-256 checksum verification before every `PPO.load()` call to prevent arbitrary code execution via malicious pickle files.

## Context
HIGH-1 from strategies security review: `PPO.load()` uses pickle internally (SB3 `.zip` files). No checksum verification before loading.

## Files to Modify/Create
- `agent/strategies/rl/runner.py:281` — add `verify_checksum()` before `PPO.load()`
- `agent/strategies/rl/deploy.py:547` — same
- `agent/strategies/rl/evaluate.py:402` — same
- `agent/strategies/ensemble/run.py:665` — same
- `agent/strategies/checksum.py` — add `strict` parameter (error vs warning)

## Acceptance Criteria
- [ ] All 4 `PPO.load()` call sites preceded by `verify_checksum(model_path)`
- [ ] Missing `.sha256` sidecar raises `SecurityError` in strict mode
- [ ] Tampered checksum raises `SecurityError`
- [ ] `strict=True` by default; `strict=False` available for development

## Dependencies
None — `verify_checksum()` utility already exists in `agent/strategies/checksum.py`

## Agent Instructions
1. Read `agent/strategies/rl/CLAUDE.md` for PPO loading patterns
2. Add `strict: bool = True` parameter to `verify_checksum()`
3. Insert verification before each `PPO.load()`:
   ```python
   from agent.strategies.checksum import verify_checksum
   verify_checksum(model_path, strict=True)
   ```
4. After any model training, generate sidecar: `save_checksum(model_path)`

## Estimated Complexity
Medium — 4 files to modify but pattern is identical
