---
task_id: 04
title: "Code Quality — Standards Compliance Review"
type: task
agent: "code-reviewer"
phase: 1
depends_on: []
status: "pending"
priority: "medium"
board: "[[customer-readiness-audit/README]]"
files:
  - "development/tasks/customer-readiness-audit/sub-reports/04-code-standards-review.md"
tags:
  - task
  - audit
  - code-review
  - standards
---

# Task 04: Code Quality — Standards Compliance Review

## Assigned Agent: `code-reviewer`

## Objective
Review the codebase for compliance with project standards documented in CLAUDE.md files. Focus on patterns that could cause customer-facing issues: error handling, API response consistency, data validation, and logging.

## Context
The project has strict conventions: Decimal for money, repository pattern, strict dependency direction (routes → services → repos → models), Pydantic v2 schemas, agent-scoped everything. Violations could cause subtle bugs customers hit.

## Areas to Review

### 1. API Response Consistency
- Check that all routes return consistent response shapes
- Verify error responses follow the `TradingPlatformError` hierarchy
- Check for any endpoints returning raw dicts instead of Pydantic schemas

### 2. Error Handling
- Scan for bare `except:` or overly broad exception catching
- Check that user-facing errors have helpful messages (not stack traces)
- Verify 400 vs 500 error classification

### 3. Money Handling
- Verify Decimal usage throughout (no float for money)
- Check for any float-to-Decimal conversion without proper rounding

### 4. Agent Isolation
- Verify all trading queries filter by `agent_id`
- Check for any cross-agent data leakage paths

### 5. Auth Consistency
- Verify all protected routes require auth
- Check for any endpoints accidentally left public

### 6. Dependency Direction
- Sample key modules and verify they don't import upward (e.g., routes importing from models directly)

## Files to Sample
Focus on customer-critical paths:
- `src/api/routes/auth.py` — registration/login
- `src/api/routes/trading.py` — order placement
- `src/api/routes/market.py` — price data
- `src/api/routes/account.py` — balance/portfolio
- `src/api/routes/battles.py` — battle system
- `src/api/routes/backtest.py` — backtesting
- `src/order_engine/engine.py` — order execution
- `src/accounts/service.py` — account management
- `src/risk/manager.py` — risk validation

## Output Format

Write findings to `development/tasks/customer-readiness-audit/sub-reports/04-code-standards-review.md`:

```markdown
# Sub-Report 04: Code Standards Compliance

**Date:** 2026-04-15
**Agent:** code-reviewer
**Overall Status:** PASS / PARTIAL / FAIL

## Standards Compliance

| Area | Status | Issues Found | Severity |
|------|--------|-------------|----------|
| API response consistency | PASS/FAIL | X | — |
| Error handling | PASS/FAIL | X | — |
| Money (Decimal) usage | PASS/FAIL | X | — |
| Agent isolation | PASS/FAIL | X | — |
| Auth consistency | PASS/FAIL | X | — |
| Dependency direction | PASS/FAIL | X | — |

## Issues Found

### High (could cause customer-facing problems)
| # | File:Line | Issue | Impact |
|---|-----------|-------|--------|
| ... | ... | ... | ... |

### Medium (code quality concern)
| # | File:Line | Issue | Impact |
|---|-----------|-------|--------|
| ... | ... | ... | ... |

### Low (style/convention)
| # | File:Line | Issue | Impact |
|---|-----------|-------|--------|
| ... | ... | ... | ... |

## Recommendations
- {prioritized list of fixes}
```

## Acceptance Criteria
- [ ] All 6 review areas checked
- [ ] At least 9 key files reviewed
- [ ] Issues categorized by severity
- [ ] Customer-facing impact assessed

## Estimated Complexity
Medium — read-only analysis of key files
