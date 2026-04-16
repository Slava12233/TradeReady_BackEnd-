---
task_id: 03
title: "Code Quality — Run Test Suite & Lint"
type: task
agent: "test-runner"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[customer-readiness-audit/README]]"
files:
  - "development/tasks/customer-readiness-audit/sub-reports/03-code-quality-tests.md"
tags:
  - task
  - audit
  - testing
  - lint
  - type-check
---

# Task 03: Code Quality — Run Test Suite & Lint

## Assigned Agent: `test-runner`

## Objective
Run the complete test suite (backend unit, integration, frontend), lint, and type checks. Produce a full health report showing pass rates, failure details, and coverage gaps. This tells us how solid the codebase is before customers start using it.

## Context
Expected numbers from context.md:
- Backend unit tests: ~2,280 across 99 files
- Backend integration tests: ~669 across 30 files (27 known pre-existing failures)
- Frontend vitest: ~735 across 47 files
- Agent tests: ~1,984 across 51 files
- Grand total: ~5,668+ tests

The CI pipeline uses `continue-on-error` for integration/agent/gym jobs due to pre-existing failures. We need to know the EXACT current state.

## Checks to Run

### 1. Backend Lint
```bash
ruff check src/ tests/ 2>&1 | tail -20
echo "Exit code: $?"
```

### 2. Backend Type Check
```bash
mypy src/ --ignore-missing-imports 2>&1 | tail -30
echo "Exit code: $?"
```

### 3. Backend Unit Tests
```bash
pytest tests/unit/ -v --tb=short -q 2>&1 | tail -50
```
Record: total, passed, failed, skipped, errors

### 4. Backend Integration Tests
```bash
pytest tests/integration/ -v --tb=short -q 2>&1 | tail -50
```
Record: total, passed, failed, skipped, errors. **Categorize every failure** — is it a real bug or a test infrastructure issue?

### 5. Frontend Tests
```bash
cd Frontend && pnpm test -- --reporter=verbose 2>&1 | tail -50
```
Record: total, passed, failed, suites

### 6. Agent Tests (if deps installed)
```bash
cd agent && pytest tests/ -v --tb=short -q 2>&1 | tail -50
```
Record: total, passed, failed, skipped

### 7. Gym Tests (if deps installed)
```bash
cd tradeready-gym && pytest tests/ -v --tb=short -q 2>&1 | tail -50
```

## Output Format

Write findings to `development/tasks/customer-readiness-audit/sub-reports/03-code-quality-tests.md`:

```markdown
# Sub-Report 03: Code Quality & Test Health

**Date:** 2026-04-15
**Agent:** test-runner
**Overall Status:** PASS / PARTIAL / FAIL

## Summary

| Suite | Total | Passed | Failed | Skipped | Pass Rate |
|-------|-------|--------|--------|---------|-----------|
| Backend Unit | X | X | X | X | X% |
| Backend Integration | X | X | X | X | X% |
| Frontend Vitest | X | X | X | X | X% |
| Agent | X | X | X | X | X% |
| Gym | X | X | X | X | X% |
| **Total** | **X** | **X** | **X** | **X** | **X%** |

## Lint & Type Check

| Check | Status | Errors | Warnings |
|-------|--------|--------|----------|
| ruff check | PASS/FAIL | X | X |
| mypy | PASS/FAIL | X | X |

## Failed Test Analysis

### Category: Real Bugs (customer-facing impact)
| Test | File | Error | Impact |
|------|------|-------|--------|
| ... | ... | ... | ... |

### Category: Test Infrastructure Issues (not customer-facing)
| Test | File | Error | Fix Needed |
|------|------|-------|------------|
| ... | ... | ... | ... |

### Category: Missing Dependencies (agent/gym not installed)
| Suite | Reason | Impact |
|-------|--------|--------|
| ... | ... | ... |

## Recommendations
- P0: {tests that indicate real bugs}
- P1: {tests to fix before launch}
- P2: {tests to fix post-launch}
```

## Acceptance Criteria
- [ ] All 7 test suites attempted (mark as SKIP if deps missing)
- [ ] Lint and type check results recorded
- [ ] Every failed test categorized (real bug vs infra vs deps)
- [ ] Pass rates calculated
- [ ] Customer-facing impact assessed for each failure

## Estimated Complexity
Medium — running tests is mechanical, but categorizing 27+ failures requires judgment
