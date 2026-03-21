---
task_id: 21
title: "Create agent activity dashboard"
type: task
agent: backend-developer
phase: 6
depends_on: [18, 19]
status: pending
priority: medium
board: "[[obsidian-integration/README]]"
files:
  - development/_dashboards/agent-activity.md
tags:
  - task
  - obsidian
  - dashboard
  - dataview
  - agents
---

# Create agent activity dashboard

## Assigned Agent: `backend-developer`

## Objective

Create `development/_dashboards/agent-activity.md` with Dataview queries and manual sections for monitoring agent workload and activity.

## Context

Complements the JSONL-based activity log with a visual dashboard. Humans can see agent workload at a glance without running scripts.

## Files to Create

- `development/_dashboards/agent-activity.md`

## Content Requirements

1. Dataview query: tasks per agent (from task frontmatter)
2. Dataview query: reviews by reviewer type
3. Manual section: link to `development/agent-activity-log.jsonl` and instructions to run `scripts/agent-run-summary.sh` and `scripts/analyze-agent-metrics.sh`
4. Dataview query: daily notes mentioning specific agents

## Acceptance Criteria

- [ ] Dashboard file exists at `development/_dashboards/agent-activity.md`
- [ ] Contains Dataview queries for tasks per agent and reviews by reviewer
- [ ] Links to JSONL activity log and shell scripts
- [ ] Instructions for running analysis scripts are included

## Estimated Complexity

Low
