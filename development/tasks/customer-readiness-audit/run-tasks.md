---
type: task
title: "Execution Guide: Customer Readiness Audit"
tags:
  - execution
  - guide
---

# Execution Guide: Customer Readiness Audit

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Verify the sub-report was written to `sub-reports/`

## Execution Order

### Phase 1: Parallel Investigation (Tasks 01-11)

**ALL tasks in Phase 1 are independent** — launch them all in parallel for maximum speed.

#### Group A: Live Platform Testing (requires production access)
These hit the live API:
- **Task 01** → `deploy-checker` — API health, Docker status, migration head
- **Task 02** → `e2e-tester` — Full user journey (register → trade → backtest)

#### Group B: Code Analysis (local only)
These read the codebase:
- **Task 03** → `test-runner` — Run full test suite + lint + type check
- **Task 04** → `code-reviewer` — Standards compliance review
- **Task 06** → `security-auditor` — OWASP Top 10 audit
- **Task 08** → `perf-checker` — Performance regression scan
- **Task 09** → `codebase-researcher` — Feature completeness matrix

#### Group C: Frontend & UX (requires browser)
- **Task 05** → `frontend-developer` — Page-by-page UX walkthrough

#### Group D: Infrastructure (requires production access)
- **Task 07** → `deploy-checker` — Monitoring, backups, reliability

#### Group E: Research & Planning (web research)
- **Task 10** → `planner` — Competitive landscape research
- **Task 11** → `planner` — Marketing readiness checklist

### Phase 2: Synthesis (Task 12)

**Depends on ALL Phase 1 tasks completing.** Do not start until all 11 sub-reports exist.

- **Task 12** → `context-manager` — Merge sub-reports into final CUSTOMER-READINESS-REPORT.md

## Parallel Execution Strategy

For maximum speed, launch ALL Phase 1 tasks simultaneously:

```
Agent(subagent_type="deploy-checker", prompt="Task 01: ...") ─┐
Agent(subagent_type="e2e-tester", prompt="Task 02: ...")      ─┤
Agent(subagent_type="test-runner", prompt="Task 03: ...")      ─┤
Agent(subagent_type="code-reviewer", prompt="Task 04: ...")    ─┤
Agent(subagent_type="frontend-developer", prompt="Task 05: ...") ─┤  All parallel
Agent(subagent_type="security-auditor", prompt="Task 06: ...") ─┤
Agent(subagent_type="deploy-checker", prompt="Task 07: ...")   ─┤
Agent(subagent_type="perf-checker", prompt="Task 08: ...")     ─┤
Agent(subagent_type="codebase-researcher", prompt="Task 09: ...") ─┤
Agent(subagent_type="planner", prompt="Task 10: ...")          ─┤
Agent(subagent_type="planner", prompt="Task 11: ...")          ─┘
                              │
                    Wait for all to complete
                              │
Agent(subagent_type="context-manager", prompt="Task 12: ...")  ← Sequential
```

## Post-Task Checklist

This is an AUDIT — no code changes expected. The standard post-change pipeline (code-reviewer → test-runner → context-manager) does NOT apply.

Instead, after Phase 2:
- [ ] Verify all 11 sub-reports exist in `sub-reports/`
- [ ] Verify final report exists at `CUSTOMER-READINESS-REPORT.md`
- [ ] Review the Go/No-Go recommendation
- [ ] Share with project owner for decision

## Estimated Timeline

| Phase | Tasks | Est. Time | Mode |
|-------|-------|-----------|------|
| Phase 1 | 01-11 | 30-60 min | Parallel |
| Phase 2 | 12 | 15-20 min | Sequential |
| **Total** | **12** | **45-80 min** | |

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Production API unreachable | Tasks 01, 02, 07 will fail — report as P0 blocker |
| Test suite has import errors | Record as finding, don't block other tasks |
| Browser tool unavailable | Task 05 can be done via code analysis instead |
| Web search unavailable | Task 10 can use codebase knowledge + general AI knowledge |
