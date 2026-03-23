---
task_id: 3
title: "Create sample report showing expected output quality"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1]
status: "pending"
priority: "medium"
board: "[[c-level-report-skill/README]]"
files:
  - ".claude/skills/c-level-report/examples/sample-report.md"
tags:
  - task
  - skill
  - example
---

# Task 3: Create Sample Report Example

## Assigned Agent: `backend-developer`

## Objective

Create a complete, realistic sample report at `.claude/skills/c-level-report/examples/sample-report.md` that demonstrates the expected quality, tone, and formatting for C-level reports.

## Context

This example teaches Claude the expected quality bar. It must use realistic data based on the actual project state (as of 2026-03-23) and demonstrate every visual element. Claude references this example when generating real reports.

## Dependencies

- **Task 1** must be complete — the sample must align with the SKILL.md section definitions

## Files to Create

- `.claude/skills/c-level-report/examples/sample-report.md` — Complete example report

## Requirements

### Use realistic data from the actual project:
- 37/37 master plan tasks complete
- 2,400+ tests (1,184 unit + 504 integration + 1,133 agent + 207 frontend)
- 22 backend modules, 130+ frontend components
- 16 agents, 7 skills (including this new one), 90+ API endpoints
- 5 trading strategies, 7 Gymnasium environments
- 6 Grafana dashboards, 11 Prometheus alert rules, 8 Docker services
- Trading goal: 10% monthly return, Sharpe >= 1.5, max drawdown <= 8%

### Demonstrate every visual element:
- KPI dashboard table with progress bars at varying levels
- Phase completion bars (Phases 0-5 at 100%, Phase 6 at ~40%)
- Risk matrix table with 4-5 entries at different severity levels
- Agent fleet inventory table
- Strategy status table
- Trend arrows (even if hypothetical — mark as "example data")

### Tone and style:
- Professional, executive-level language
- Lead with outcomes and impact, not technical implementation
- Use specific numbers everywhere — no "several" or "many"
- Bold key metrics inline: "Test coverage reached **2,400+ tests**"
- Include "so what?" context: why each metric matters

### Length:
- 250-350 lines of markdown
- Executive summary: 5-8 sentences

## Agent Instructions

Before writing, read these files for accurate data:
1. `development/context.md` (first 100 lines)
2. Root `CLAUDE.md` (architecture section)
3. `development/trading-agent-master-plan.md` (first 80 lines — executive summary)

Use real project data to make the sample authentic.

## Acceptance Criteria

- [ ] File exists at `.claude/skills/c-level-report/examples/sample-report.md`
- [ ] All 11 sections present with realistic project data
- [ ] All visual elements demonstrated (progress bars, status icons, tables, trend arrows)
- [ ] Executive-appropriate tone (readable by non-technical leadership)
- [ ] Length between 250-350 lines
- [ ] Frontmatter included matching the template format

## Estimated Complexity

**Medium** — Requires synthesizing real project data into executive-style writing with rich formatting.
