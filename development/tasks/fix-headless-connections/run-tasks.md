---
type: task
tags:
  - execution-guide
  - headless-env
date: 2026-04-08
---

# Execution Guide: Fix HeadlessTradingEnv DB Connections

## How to Run Tasks

### Phase 1 (sequential)
- Task 1: Implement fix → `ml-engineer`
- Task 2: Update tests → `test-runner`

### Phase 2 (after Phase 1)
- Task 3: Smoke test in Docker → `ml-engineer`

## Post-Task Checklist
After Task 1:
- [ ] `ruff check` passes
- [ ] Code matches plan exactly

After Task 2:
- [ ] All 52+ existing tests pass
- [ ] 4 new connection management tests pass

After Task 3:
- [ ] PPO training runs for 2048 steps without errors
- [ ] Model saved to `models/ppo_btc_v1.zip`
- [ ] Commit all changes and push
