---
task_id: 28
title: "Update context-manager daily note step"
type: task
agent: context-manager
phase: 9
depends_on: [22, 24]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - .claude/agents/context-manager.md
tags:
  - task
  - obsidian
  - agent-update
  - daily-notes
  - context-manager
---

# Update context-manager daily note step

## Assigned Agent: `context-manager`

## Objective

Add instructions to the context-manager agent's workflow for daily note maintenance, connecting the existing context-manager workflow to the daily note system.

## Context

The context-manager already runs after every task, so daily notes get populated automatically. The change is additive (new optional step), and the context-manager uses Edit tool (not Write), so it won't clobber human-written content in the "Human Notes" section.

## Files to Modify

- `.claude/agents/context-manager.md`

## Change

Add a new Step 6.5 between existing Steps 6 and 7:

```
### Step 6.5: Update Daily Note

If `development/daily/YYYY-MM-DD.md` exists for today, append a summary of changes
to the "Agent Activity" section. If the daily note doesn't exist, run:
```bash
bash scripts/create-daily-note.sh
```
Then append the summary. Format:

### Changes Made
- `path/to/file.py` -- one-line description

### Decisions
- Decision and reasoning

### Issues Found
- Issue description
```

## Acceptance Criteria

- [ ] `.claude/agents/context-manager.md` includes the new Step 6.5
- [ ] Step references `scripts/create-daily-note.sh` for creating missing notes
- [ ] Activity summary format is documented
- [ ] Existing workflow steps are preserved
- [ ] New step is clearly marked as between existing Steps 6 and 7

## Estimated Complexity

Low
