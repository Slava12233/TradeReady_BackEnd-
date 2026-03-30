---
task_id: R2-06
title: "Checksum verification before joblib.load()"
type: task
agent: "security-reviewer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["agent/strategies/regime/classifier.py"]
tags:
  - task
  - security
  - ml
  - deserialization
---

# Task R2-06: Checksum Verification Before `joblib.load()`

## Assigned Agent: `security-reviewer`

## Objective
Enforce SHA-256 checksum verification and payload structure validation before loading regime classifier models.

## Context
HIGH-2 from strategies security review: `joblib.load()` for regime classifier has same pickle risk as PPO.

## Files to Modify/Create
- `agent/strategies/regime/classifier.py:406` — add checksum + structure check

## Acceptance Criteria
- [ ] `verify_checksum(path)` called before `joblib.load(path)`
- [ ] Post-load structure check: payload is dict with `"classifier"` key
- [ ] Missing checksum or tampered file raises `SecurityError`
- [ ] Invalid payload structure raises `SecurityError`

## Dependencies
None — same pattern as R2-05

## Agent Instructions
1. Add before `joblib.load()`:
   ```python
   from agent.strategies.checksum import verify_checksum
   verify_checksum(path, strict=True)
   payload = joblib.load(path)
   if not isinstance(payload, dict) or "classifier" not in payload:
       raise SecurityError(f"Unexpected payload structure in {path}")
   ```

## Estimated Complexity
Medium — single file but adds both pre-load and post-load validation
