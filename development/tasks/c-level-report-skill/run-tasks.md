---
type: task
tags:
  - execution-guide
  - c-level-report
---

# Execution Guide: C-Level Executive Report Skill

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents after Phase 2

## Execution Order

### Phase 1: Create Skill Files

**Parallel group A** (no dependencies):
- Task 1: `backend-developer` — Write SKILL.md
- Task 2: `backend-developer` — Create report template

**Sequential after group A:**
- Task 3: `backend-developer` — Create sample report (depends on Task 1)

### Phase 2: Documentation Updates

**Sequential after Phase 1:**
- Task 4: `doc-updater` — Update CLAUDE.md navigation + create output directory

### Phase 3: Context Sync

**Sequential after Phase 2:**
- Task 5: `context-manager` — Update context.md + daily note

## Post-Completion Quality Gate

After all 5 tasks complete:
- [ ] `code-reviewer` validates all new files against project standards
- [ ] `test-runner` checks for any regressions
- [ ] Manual test: run `/c-level-report` and verify output quality
- [ ] Manual test: run `/c-level-report risk` and verify scoped output
- [ ] Verify report saves to `development/C-level_reports/report-YYYY-MM-DD.md`

## Quick Start

To begin, delegate Tasks 1 and 2 to `backend-developer` in parallel:

```
Agent(backend-developer): "Execute Task 1 from development/tasks/c-level-report-skill/task-01-create-skill-md.md"
Agent(backend-developer): "Execute Task 2 from development/tasks/c-level-report-skill/task-02-create-report-template.md"
```
