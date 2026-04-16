---
task_id: 06
title: "Security Audit — Full OWASP Scan"
type: task
agent: "security-auditor"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[customer-readiness-audit/README]]"
files:
  - "development/tasks/customer-readiness-audit/sub-reports/06-security-audit.md"
tags:
  - task
  - audit
  - security
  - owasp
---

# Task 06: Security Audit — Full OWASP Scan

## Assigned Agent: `security-auditor`

## Objective
Perform a comprehensive security audit of the platform codebase, focusing on the OWASP Top 10 and platform-specific risks (agent isolation, API key handling, money manipulation). This is critical — a security breach would kill customer trust immediately.

## Context
Previous security reviews (2026-03-20, 2026-03-23, 2026-04-07):
- All 7 HIGH findings resolved as of 2026-03-23
- SSRF protection added for webhooks (2026-04-07)
- 9 security findings resolved in V.0.0.3 audit
- Agent isolation, budget enforcement, permission system all audited

But there may be NEW issues from code written since the last audit, and the previous audits focused on agent strategies — not the customer-facing API surface.

## Areas to Audit

### 1. Authentication & Authorization
- `src/api/middleware/auth.py` — API key and JWT flow
- `src/accounts/auth.py` — Key generation, password hashing, JWT creation
- Check: Can an unauthenticated user access protected endpoints?
- Check: Can Agent A access Agent B's data?
- Check: JWT expiry and refresh flow

### 2. Injection Risks
- `src/api/routes/*.py` — All route handlers
- `src/database/repositories/*.py` — All DB queries
- Check: SQLAlchemy parameterized queries throughout?
- Check: Any raw SQL or string interpolation in queries?

### 3. Rate Limiting
- `src/api/middleware/rate_limit.py`
- Check: Rate limiting on registration (brute force)
- Check: Rate limiting on login (credential stuffing)
- Check: Rate limiting on trading (abuse)

### 4. Data Exposure
- Check: API responses don't leak internal IDs, stack traces, or other users' data
- Check: Password hashes never returned
- Check: API keys shown only once at creation
- Check: Error messages don't reveal system internals

### 5. CORS & Headers
- `src/main.py` — CORS configuration
- Check: Only tradeready.io domains allowed
- Check: Security headers (HSTS, X-Frame-Options, CSP)

### 6. Secret Management
- `.env.example` — What secrets are needed
- Check: No hardcoded secrets in source code
- Check: `.env` is in `.gitignore`
- Check: No secrets in CI logs

### 7. Webhook Security (new in V.0.0.3)
- `src/webhooks/dispatcher.py` — SSRF protection
- Check: Private IP blocking works
- Check: HMAC signing implemented correctly

### 8. Agent Isolation
- Check: All trading queries scoped by agent_id
- Check: No cross-agent data access possible via API
- Check: Agent deletion cascades properly (migration 021)

## Output Format

Write findings to `development/tasks/customer-readiness-audit/sub-reports/06-security-audit.md`:

```markdown
# Sub-Report 06: Security Audit

**Date:** 2026-04-15
**Agent:** security-auditor
**Overall Status:** PASS / CONDITIONAL PASS / FAIL

## OWASP Top 10 Assessment

| Category | Status | Findings |
|----------|--------|----------|
| A01: Broken Access Control | PASS/FAIL | X |
| A02: Cryptographic Failures | PASS/FAIL | X |
| A03: Injection | PASS/FAIL | X |
| A04: Insecure Design | PASS/FAIL | X |
| A05: Security Misconfiguration | PASS/FAIL | X |
| A06: Vulnerable Components | PASS/FAIL | X |
| A07: Auth Failures | PASS/FAIL | X |
| A08: Data Integrity | PASS/FAIL | X |
| A09: Logging & Monitoring | PASS/FAIL | X |
| A10: SSRF | PASS/FAIL | X |

## Platform-Specific Security

| Area | Status | Findings |
|------|--------|----------|
| Agent isolation | PASS/FAIL | X |
| Money handling | PASS/FAIL | X |
| API key security | PASS/FAIL | X |
| Rate limiting | PASS/FAIL | X |
| Webhook SSRF | PASS/FAIL | X |

## Findings

### CRITICAL (must fix before ANY customer access)
| # | File:Line | Vulnerability | Impact | Remediation |
|---|-----------|--------------|--------|-------------|

### HIGH (must fix before marketing push)
| # | File:Line | Vulnerability | Impact | Remediation |
|---|-----------|--------------|--------|-------------|

### MEDIUM (fix within 2 weeks of launch)
| # | File:Line | Vulnerability | Impact | Remediation |
|---|-----------|--------------|--------|-------------|

### LOW (accept for now)
| # | File:Line | Vulnerability | Impact | Remediation |
|---|-----------|--------------|--------|-------------|

## Recommendations
- {prioritized security fixes}
```

## Acceptance Criteria
- [ ] All 8 security areas audited
- [ ] OWASP Top 10 checklist completed
- [ ] Every finding has severity, file location, and remediation
- [ ] CRITICAL/HIGH findings flagged as launch blockers
- [ ] No false positives — each finding verified in code

## Estimated Complexity
High — requires deep code reading across multiple modules
