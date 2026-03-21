---
task_id: 13
title: "Create /analyze-agents skill"
type: task
agent: "backend-developer"
phase: 3
depends_on: [9, 11]
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "medium"
files:
  - ".claude/skills/analyze-agents/SKILL.md"
tags:
  - task
  - agent
  - memory
---

# Task 13: Create /analyze-agents skill

## Assigned Agent: `backend-developer`

## Objective
Create a new Claude Code skill (`/analyze-agents`) that reads the agent activity log, analyzes patterns, identifies recurring issues, and suggests agent prompt improvements.

## Context
Phase 3 of Agent Memory Strategy. This skill closes the feedback loop — it reads what agents did (from the JSONL log) and recommends how to make them better.

## Files to Create
- `.claude/skills/analyze-agents/SKILL.md`

## Implementation Details

The skill should instruct Claude to:

1. Read `development/agent-activity-log.jsonl` for raw events
2. Read `development/agent-runs/` for run summaries
3. Read `.claude/agent-memory/*/MEMORY.md` for current agent knowledge
4. Analyze patterns:
   - Which tools does each agent use most?
   - Which files are modified most frequently?
   - Are there recurring patterns in agent activity?
   - What patterns appear in agent memory that could be consolidated?
5. Generate a report with:
   - Agent activity summary (runs, tools, files)
   - Suggested memory updates (new patterns to add, stale entries to remove)
   - Agent prompt improvement recommendations
6. Save report to `development/agent-analysis/report-{date}.md`

## Acceptance Criteria
- [ ] Skill file created at `.claude/skills/analyze-agents/SKILL.md`
- [ ] Skill follows existing skill format (see `.claude/skills/commit/SKILL.md` for reference)
- [ ] Reads activity log and agent memory files
- [ ] Generates actionable improvement recommendations
- [ ] Saves report to `development/agent-analysis/`

## Agent Instructions
Read existing skills in `.claude/skills/` for format conventions. The skill should be invocable as `/analyze-agents` and produce a comprehensive but actionable report. Focus on patterns that can be turned into agent prompt updates or memory entries.

## Estimated Complexity
Medium — requires thoughtful prompt design for the analysis workflow.
