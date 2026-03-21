---
task_id: 14
title: "Update /review-changes skill with feedback capture"
type: task
agent: "backend-developer"
phase: 3
depends_on: [12]
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "medium"
files:
  - ".claude/skills/review-changes/SKILL.md"
tags:
  - task
  - agent
  - memory
---

# Task 14: Update /review-changes skill with feedback capture

## Assigned Agent: `backend-developer`

## Objective
Modify the `/review-changes` skill to capture user feedback on agent findings (accept/reject) and log it to the activity log for future analysis.

## Context
Phase 3 of Agent Memory Strategy. Currently the review-changes pipeline runs agents but doesn't track whether their findings were useful. Adding feedback capture enables measuring agent accuracy and driving improvements.

## Files to Modify
- `.claude/skills/review-changes/SKILL.md` — add feedback capture step

## Implementation Details

After the pipeline completes (code-reviewer → test-runner → context-manager), add a step that:

1. Summarizes findings from the code-reviewer report
2. Asks the user: "Were these findings helpful? [all-useful / some-useful / not-useful]"
3. Logs the feedback to `development/agent-activity-log.jsonl`:
   ```json
   {
     "ts": "2026-03-21T10:30:00Z",
     "tool": "feedback",
     "target": "code-reviewer",
     "feedback": "some-useful",
     "report": "development/code-reviews/review-{date}.md"
   }
   ```
4. If feedback is "not-useful", ask for a brief reason (optional)
5. Update the agent's MEMORY.md with the feedback pattern

## Acceptance Criteria
- [ ] Skill file updated with feedback capture step
- [ ] Feedback options are simple (3 choices max)
- [ ] Feedback is logged to JSONL activity log
- [ ] Reason capture is optional (don't block workflow)
- [ ] Existing pipeline behavior is unchanged (feedback is additive)
- [ ] Agent memory is updated based on feedback

## Agent Instructions
Read the current `.claude/skills/review-changes/SKILL.md` first. Add the feedback step at the END of the pipeline (after context-manager). Use Claude's built-in user interaction to ask for feedback. Keep it lightweight — the goal is data collection, not a survey.

## Estimated Complexity
Medium — requires modifying an existing skill while preserving its pipeline logic.
