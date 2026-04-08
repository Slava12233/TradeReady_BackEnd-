---
task_id: 7
title: "Run full test suite + lint + type check"
type: task
agent: "test-runner"
phase: 2
depends_on: [5]
status: "pending"
priority: "high"
board: "[[v003-next-steps/README]]"
files: []
tags:
  - task
  - testing
  - validation
---

# Task 07: Run full test suite + lint + type check

## Assigned Agent: `test-runner`

## Objective
Run the complete platform test suite to verify zero regressions from all V.0.0.3 changes.

## Context
V.0.0.3 added 7 improvements (64 files changed, 14K+ lines) plus security fixes. Must verify the entire existing test suite (1,700+ tests) still passes.

## Acceptance Criteria
- [ ] `pytest tests/unit/ -x -q` — all pass
- [ ] `pytest tests/integration/ -x -q` — all pass (Docker services running)
- [ ] `ruff check src/ tests/` — zero errors
- [ ] `mypy src/` — passes
- [ ] All 397+ new endgame tests pass
- [ ] Report total test count and pass rate

## Dependencies
- **Task 5** (security fix tests) — ensures all fixes are tested before full validation

## Agent Instructions
1. Run unit tests first (fastest feedback loop)
2. Run lint and type check in parallel
3. Run integration tests last (requires Docker)
4. If failures: categorize as pre-existing vs newly introduced

## Estimated Complexity
Low — running existing infrastructure, no code changes.
