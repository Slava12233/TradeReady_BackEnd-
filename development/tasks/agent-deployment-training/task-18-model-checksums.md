---
task_id: 18
title: "Add model checksum verification"
agent: "security-reviewer"
phase: 9
depends_on: []
status: "completed"
priority: "high"
files: ["agent/strategies/rl/deploy.py", "agent/strategies/rl/evaluate.py", "agent/strategies/rl/runner.py", "agent/strategies/regime/classifier.py", "agent/strategies/ensemble/run.py"]
---

# Task 18: Add model checksum verification

## Assigned Agent: `security-reviewer`

## Objective
Add SHA-256 checksum verification before loading pickle/joblib model files to mitigate unsafe deserialization (HIGH-1 and HIGH-2 from security review).

## Approach
1. When saving a model, compute and store SHA-256 hash alongside it (`.sha256` sidecar file)
2. Before loading, verify the hash matches
3. If no hash file exists (legacy models), warn but allow loading (backwards compat)

## Files to Modify
1. `rl/runner.py` — save checksum when saving PPO model
2. `rl/deploy.py` — verify before `PPO.load()`
3. `rl/evaluate.py` — verify before `PPO.load()`
4. `regime/classifier.py` — save checksum in `save()`, verify in `load()`
5. `ensemble/run.py` — verify before loading any model

## Acceptance Criteria
- [ ] Models saved with `.sha256` sidecar file containing hex digest
- [ ] Loading verifies checksum matches; raises `SecurityError` on mismatch
- [ ] Missing checksum file logs WARNING but proceeds (backwards compat)
- [ ] All existing tests pass
- [ ] New tests cover: valid checksum, tampered file, missing checksum

## Dependencies
None — can start immediately.

## Agent Instructions
Read `development/code-reviews/security-review-agent-strategies.md` for full details on HIGH-1 and HIGH-2. Use `hashlib.sha256` with file read in 8KB chunks. The sidecar pattern (`.sha256` next to `.zip`/`.joblib`) is simpler than embedding checksums in a manifest.

## Estimated Complexity
Medium — 5 files to modify, new utility function, new tests.
