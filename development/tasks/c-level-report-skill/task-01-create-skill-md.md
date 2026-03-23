---
task_id: 1
title: "Write SKILL.md core workflow for c-level-report"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[c-level-report-skill/README]]"
files:
  - ".claude/skills/c-level-report/SKILL.md"
tags:
  - task
  - skill
  - c-level
---

# Task 1: Write SKILL.md Core Workflow

## Assigned Agent: `backend-developer`

## Objective

Create the main skill definition file at `.claude/skills/c-level-report/SKILL.md`. This is the core file that Claude Code reads when the user invokes `/c-level-report`. It must contain YAML frontmatter and a markdown body defining the complete report generation workflow.

## Context

This is the highest-priority task — the quality of every future executive report depends on this file. See `development/c-level-report-skill-plan.md` for the full design spec.

## Files to Create

- `.claude/skills/c-level-report/SKILL.md` — Main skill definition

## Required YAML Frontmatter

```yaml
---
name: c-level-report
description: >
  Generate a comprehensive C-level executive report analyzing project progress,
  architecture maturity, code quality, agent team status, risk posture, and
  strategic roadmap. Saves to development/C-level_reports/. Use when leadership
  needs a full project status update.
user-invocable: true
allowed-tools: Read, Write, Grep, Glob, Bash
model: sonnet
argument-hint: "[scope: full|progress|quality|risk|agents|roadmap]"
---
```

## Workflow Steps to Define

### Step 1: Gather Live Metrics
Instruct Claude to run bash commands collecting real-time data:
- `git log --oneline --since="30 days ago" | wc -l` — recent commit count
- `git log --oneline -10` — latest commits for activity section
- `git shortlog -sn --since="30 days ago"` — contributor activity
- `grep -r "def test_\|async def test_" tests/ agent/tests/ --include="*.py" | wc -l` — Python test count
- `find src/ -maxdepth 1 -type d | wc -l` — backend module count
- `find Frontend/src/components -name "*.tsx" | wc -l` — frontend component count
- `find .claude/agents -name "*.md" -not -name "CLAUDE.md" | wc -l` — agent fleet size
- `grep -r "@router\." src/api/routes/ --include="*.py" | wc -l` — API endpoint count
- `find development/tasks -maxdepth 1 -type d | wc -l` — task board count
- `wc -l development/agent-activity-log.jsonl 2>/dev/null || echo "0"` — agent activity entries
- `find monitoring/provisioning -name "*.json" | wc -l` — Grafana dashboard count
- `docker compose config --services 2>/dev/null | wc -l` — Docker service count

### Step 2: Read Context Files
Tell Claude to read these files:
- `development/context.md` (first 150 lines — project overview and current state)
- `development/trading-agent-master-plan.md` (first 100 lines — executive summary + phases)
- Latest 2 code review reports from `development/code-reviews/` (glob for `*.md`, sort by name, read newest 2)
- Latest daily note from `development/daily/` (most recent `.md` file)
- Agent memory: `.claude/agent-memory/security-reviewer/MEMORY.md`, `.claude/agent-memory/perf-checker/MEMORY.md`, `.claude/agent-memory/code-reviewer/MEMORY.md`

### Step 3: Check for Previous Reports (Trend Analysis)
- Glob `development/C-level_reports/report-*.md`
- If previous reports exist, read the most recent one
- Compare KPIs to show trends (↑ improved, ↓ declined, → stable)
- If no previous reports, skip trend section

### Step 4: Analyze & Generate Report
Generate markdown with these 11 sections:

**Section 1: Executive Summary**
- Report date, scope, platform one-liner
- 3-5 key highlights as bullet points
- Overall health bar: `[████████░░] 80% — On Track`

**Section 2: Project Health Dashboard**
- KPI table with columns: KPI | Current | Target | Status | Progress
- Progress column uses `[██████████] 100%` format (10 chars)
- Status uses: ✅ MET, ⚠️ AT RISK, ❌ MISSED, 🔄 IN PROGRESS

**Section 3: Architecture Overview**
- Core component table (14 components from root CLAUDE.md)
- Technology stack summary
- Key data flow descriptions (1-2 sentences each)

**Section 4: Progress & Milestones**
- Phase completion bars (6 phases)
- Recent achievements (from git log + daily notes)
- Task board completion summary table

**Section 5: Code Quality & Testing**
- Test inventory breakdown by category (unit, integration, agent, frontend)
- Latest code review verdict + findings summary
- Quality metrics (lint, type-check status)

**Section 6: Agent Team Status**
- Agent fleet inventory table (name, role, model, status)
- Pipeline descriptions
- Key agent learnings from memory files

**Section 7: Trading System Status**
- 5-strategy inventory with status
- Trading goal: 10% monthly target
- Gymnasium environments and battle system status

**Section 8: Risk Assessment**
- Risk matrix table (Risk | Severity | Likelihood | Mitigation | Owner)
- Security posture from security-reviewer memory
- Performance risks from perf-checker memory
- Technical debt items

**Section 9: Infrastructure & Operations**
- Docker services table
- Monitoring stack (dashboards, alerts)
- CI/CD status

**Section 10: Strategic Roadmap**
- Near-term (7-14 days), medium-term (30-60 days), long-term (Q2-Q3 2026)
- Key decision points

**Section 11: Recommendations**
- Top 5 prioritized, actionable recommendations
- Each with: what, why, expected impact

### Step 5: Save Report
- Create `development/C-level_reports/` if it doesn't exist
- Write to `development/C-level_reports/report-YYYY-MM-DD.md`
- Include Obsidian frontmatter: `type: c-level-report`, `date`, `scope`, `generated-by`, `tags`
- If file exists for today, use `report-YYYY-MM-DD-HHMMSS.md`

### Step 6: Display Terminal Summary
- Show report saved path
- Show 5-line executive summary
- Show top 3 recommendations
- Show key KPI changes (if trend data available)

### Scoping via $ARGUMENTS
Define scope handling:
- `full` or empty → all 11 sections
- `progress` → sections 1, 2, 4, 10
- `quality` → sections 1, 2, 5, 8
- `risk` → sections 1, 2, 8, 9, 11
- `agents` → sections 1, 2, 6, 7
- `roadmap` → sections 1, 2, 4, 10, 11

### Rules Section
1. All metrics must be gathered at runtime via Bash/Grep/Glob — never hardcode numbers
2. Progress bars use `[████████░░] 80%` (10-char width, block characters ██ for filled, ░░ for empty)
3. Status: ✅ On track, ⚠️ At risk, ❌ Critical, 🔄 In progress
4. Tables must be properly aligned markdown with header separators
5. Report must include generation timestamp in frontmatter AND body
6. If a data source is unavailable, write "Data unavailable" — never fabricate
7. All bash commands must use forward slashes and Git Bash compatible syntax
8. Reference the template in `templates/report-template.md` for structure
9. Reference the example in `examples/sample-report.md` for tone and quality

## Acceptance Criteria

- [ ] File exists at `.claude/skills/c-level-report/SKILL.md`
- [ ] Frontmatter has all required fields
- [ ] All 6 workflow steps are documented with specific commands and file paths
- [ ] All 11 report sections are defined with their data sources
- [ ] Scoping via `$ARGUMENTS` is implemented for 6 scopes
- [ ] Rules section has all 9 rules
- [ ] File is under 400 lines (keep focused, details go in template/example)

## Estimated Complexity

**High** — Core skill definition that determines the quality of all future reports.
