---
task_id: 22
title: "Security review of risk management changes"
type: task
agent: "security-reviewer"
phase: 2
depends_on: [16, 17, 18, 19, 20, 21]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/risk/"]
tags:
  - task
  - security
  - risk
---

# Task 22: Security review of risk changes

## Assigned Agent: `security-reviewer`

## Objective
Audit all Phase 2 risk management changes for security vulnerabilities: float precision issues with Decimal money values, TOCTOU races in Redis-based circuit breakers, fail-open risks in new risk gates.

## Focus Areas
- Position sizing calculations use `Decimal`, never `float`
- Redis circuit breaker operations are atomic (no TOCTOU)
- New risk gates fail-closed (deny trade if checks fail)
- Recovery protocol can't be bypassed
- No injection risks in Redis key construction

## Acceptance Criteria
- [ ] No float arithmetic on monetary values
- [ ] All Redis operations atomic or properly locked
- [ ] All new risk gates fail-closed
- [ ] CRITICAL issues fixed immediately
- [ ] Security audit report generated

## Estimated Complexity
Medium — reviewing 6 tasks worth of risk code.
