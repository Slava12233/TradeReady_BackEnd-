---
task_id: 6
title: "Security re-audit of fixed code"
type: task
agent: "security-auditor"
phase: 1
depends_on: [1, 2, 3, 4, 5]
status: "pending"
priority: "high"
board: "[[v003-next-steps/README]]"
files:
  - "src/api/schemas/webhooks.py"
  - "src/api/schemas/metrics.py"
  - "src/webhooks/dispatcher.py"
  - "src/tasks/webhook_tasks.py"
tags:
  - task
  - security
  - audit
  - verification
---

# Task 06: Security re-audit of fixed code

## Assigned Agent: `security-auditor`

## Objective
Verify that all CRITICAL/HIGH/MEDIUM findings from the original audit are resolved.

## Context
Tasks 1-4 fix the security findings. This task re-audits the specific files to confirm all issues are resolved and no new issues were introduced.

## Files to Modify/Create
- Read-only audit of all modified files
- Report saved to `development/code-reviews/`

## Acceptance Criteria
- [ ] SSRF: webhook URLs validated, private IPs blocked, HTTPS enforced
- [ ] DoS: returns array bounded, auth required on metrics endpoint
- [ ] Secret: no longer passed as Celery task arg, fetched from DB
- [ ] Limits: per-account webhook cap enforced
- [ ] Validator: ranking_metric uses proper @field_validator
- [ ] session_id: UUID type in backtest routes
- [ ] Cache key: 16-char hash
- [ ] Logs: URL redacted
- [ ] No new findings introduced
- [ ] Verdict: PASS (upgrade from CONDITIONAL PASS)

## Dependencies
- **All security fix and test tasks (1-5)** must complete first

## Agent Instructions
1. Read each fixed file and verify the specific finding is resolved
2. Check for regressions or new issues introduced by the fixes
3. Save report to `development/code-reviews/security-re-audit-v003.md`
4. Expected verdict: PASS

## Estimated Complexity
Low — targeted verification of known fixes.
