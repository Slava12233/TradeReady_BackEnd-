---
task_id: 7
title: "Add frontmatter to planning docs"
type: task
agent: backend-developer
phase: 2
depends_on: [1]
status: pending
priority: medium
board: "[[obsidian-integration/README]]"
files:
  - development/developmantPlan.md
  - development/developmentprogress.md
  - development/tasks.md
  - development/codereviewplan.md
  - development/codereviewtasks.md
  - development/agentic-layer-plan-tasks.md
  - development/agents-backtesting-battles-research.md
  - development/backtesting_tasks.md
  - development/backtestingdevelopment.md
  - development/multiagent_battle_tasks.md
  - development/multiagent_fix_tasks.md
  - development/Multiagentbattleplan.md
  - development/integration_tasks.md
  - development/test_coverage_tasks.md
  - development/gap_fill_implementation_plan.md
  - development/market_data_gap_fill.md
  - development/platform-tools-report.md
  - development/agent-trading-strategy-report.md
  - development/data-pipeline-report.md
  - development/plan.md
  - development/executive-summary.md
  - development/agent-ecosystem-plan.md
  - development/agent-memory-strategy-report.md
  - development/agent-logging-research.md
  - development/agent-logging-plan.md
  - development/docs-plan-task.md
  - development/agent-development/agent_plan.md
  - development/agent-development/tasks.md
  - development/agent-development/agent-strategies-report.md
  - development/agent-development/agent-strategies-cto-brief.md
  - development/agent-development/battle-historical-investigation.md
tags:
  - task
  - obsidian
  - frontmatter
  - planning-docs
---

# Add frontmatter to planning docs

## Assigned Agent: `backend-developer`

## Objective

Add YAML frontmatter to the ~30 standalone planning docs and research reports in `development/` so they are discoverable through Dataview queries and tag-based navigation.

## Context

These files are archived and frozen per `development/CLAUDE.md` rules. Adding frontmatter does not modify their content. Tags enable cross-referencing (e.g., all docs related to "battles").

## Type Mapping Rules

- Files ending in `plan.md` or `Plan.md` -> `type: plan`
- Files ending in `tasks.md` -> `type: task-list`
- Files ending in `report.md` or `research.md` -> `type: research-report`
- Files with `investigation` in name -> `type: investigation`
- `executive-summary.md` -> `type: executive-summary`
- `developmentprogress.md` -> `type: progress-tracker`

## Frontmatter Format (varies by type)

```yaml
---
type: plan
title: Agent Ecosystem Plan
created: 2026-03-20
status: archived
phase: agent-ecosystem
tags:
  - plan
  - agent-ecosystem
---
```

## Acceptance Criteria

- [ ] All ~30 planning docs have valid YAML frontmatter
- [ ] `type` field matches the type mapping rules
- [ ] `status` is `archived` for frozen docs, `active` for maintained docs, `complete` for finished projects
- [ ] Tags are relevant to content keywords
- [ ] Existing file content is preserved unchanged below the frontmatter

## Estimated Complexity

High (30+ files, but mechanical)
