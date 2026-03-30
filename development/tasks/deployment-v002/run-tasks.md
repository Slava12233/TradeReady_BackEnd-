---
type: task
title: "Execution Guide: Deployment V.0.0.2"
tags:
  - execution
  - deployment
---

# Execution Guide: Deployment V.0.0.2

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager) after code changes

## Execution Order

### Already Completed (4 tasks)
- Task 01: Fix ruff lint errors — `backend-developer` — DONE
- Task 02: Fix ruff format violations — `backend-developer` — DONE
- Task 05: CI/CD pipeline fixes — `backend-developer` — DONE
- Task 06: CORS env-driven configuration — `backend-developer` — DONE

### Next: Fix CI Failures (2 tasks, sequential)
- **Task 03**: Run mypy and fix type errors → `backend-developer`
- **Task 04**: Run unit tests and fix failures → `test-runner` (after Task 03)

### Parallel Verification (4 tasks)
After Tasks 03-04 pass, these can run in parallel:
- **Task 07**: Verify migration chain → `migration-helper`
- **Task 08**: Verify migration safety → `migration-helper` (after Task 07)
- **Task 09**: Security audit → `security-auditor`
- **Task 10**: Code review → `code-reviewer`

### Final Test (1 task)
- **Task 11**: Run full unit test suite → `test-runner`

### Deploy Gate (1 task)
- **Task 12**: Pre-deploy checklist → `deploy-checker`

### Push & Deploy (2 tasks, sequential)
- **Task 13**: Commit and push to main → `backend-developer`
- **Task 14**: Server-side deploy → `deploy-checker`

### Post-Deploy (2 tasks, sequential)
- **Task 15**: Post-deployment validation → `e2e-tester`
- **Task 16**: Update context → `context-manager`

## Post-Task Checklist
After each code-changing task completes:
- [ ] code-reviewer agent validates the changes
- [ ] test-runner agent runs relevant tests
- [ ] context-manager agent logs what changed
