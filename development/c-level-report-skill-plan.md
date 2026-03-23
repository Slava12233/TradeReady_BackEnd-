---
type: plan
tags:
  - skill
  - c-level
  - reporting
  - executive
created: 2026-03-23
status: ready-to-implement
---

# Plan: C-Level Executive Report Skill (`/c-level-report`)

## Objective

Create a reusable Claude Code skill that generates a comprehensive, professional C-level executive report about the AI Trading Agent platform. The report covers project status A-Z — progress, architecture, quality, risk, agent team, roadmap — and saves to `development/C-level_reports/` for historical tracking.

---

## Research Summary

### Data Sources Available

The skill will aggregate data from **12 categories** of project intelligence:

| # | Source | Path | What It Provides |
|---|--------|------|------------------|
| 1 | Rolling context | `development/context.md` | Current state, what's built, decisions, known issues |
| 2 | Master plan | `development/trading-agent-master-plan.md` | 6-phase roadmap, success metrics, task inventory |
| 3 | Task boards | `development/tasks/*/` | 11 task boards with completion status per task |
| 4 | Daily notes | `development/daily/*.md` | Day-by-day activity, human notes, agent logs |
| 5 | Code reviews | `development/code-reviews/*.md` | Quality verdicts, issues found, files reviewed |
| 6 | Agent memory | `.claude/agent-memory/*/MEMORY.md` | Cross-session learnings, patterns, feedback |
| 7 | Agent activity log | `development/agent-activity-log.jsonl` | Structured log of all agent actions |
| 8 | Git history | `git log` / `git shortlog` | Commit velocity, feature delivery timeline |
| 9 | Architecture docs | `CLAUDE.md` (root + 37 module files) | Module inventory, API count, component count |
| 10 | Test inventory | `tests/` + `agent/tests/` + `Frontend/` | Test counts, coverage, file inventory |
| 11 | Monitoring config | `monitoring/` | Dashboards, alert rules, metrics exposed |
| 12 | Docker/infra | `docker-compose.yml`, `pyproject.toml` | Services, dependencies, runtime config |

### Skill Architecture (Based on Existing Skills)

Existing skills follow this pattern:
- **One `SKILL.md` file** per skill in `.claude/skills/{name}/SKILL.md`
- **YAML frontmatter** with `name`, `description`, `allowed-tools`, `user-invocable`
- **Markdown body** with numbered steps, rules, and output format
- **Dynamic data injection** via `` !`command` `` syntax (runs before Claude processes)
- **Supporting files** (templates, examples) in subdirectories

### User Preferences (from interview)

| Setting | Choice |
|---------|--------|
| Frequency | On-demand (`/c-level-report`) |
| Sections | Full A-Z coverage |
| Output | Save to `development/C-level_reports/report-YYYY-MM-DD.md` |
| Visuals | Rich formatting (progress bars, ASCII charts, status indicators) |

---

## Skill Design

### File Structure

```
.claude/skills/c-level-report/
├── SKILL.md                          # Main skill definition (frontmatter + workflow)
├── templates/
│   └── report-template.md            # Report skeleton with section structure
└── examples/
    └── sample-report.md              # Example output for Claude to reference
```

### Output Structure

```
development/C-level_reports/
├── report-2026-03-23.md              # Individual reports (one per run)
├── report-2026-03-30.md
└── ...
```

### Frontmatter

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

**Note:** `Write` tool is needed because the skill saves reports to file.

---

## Report Sections (Full A-Z)

### Section 1: Executive Summary Header
- Report date, period covered, report scope
- Platform name and one-line description
- 3-5 key highlights (auto-generated from data)
- Overall health indicator: `[████████░░] 80% — On Track`

### Section 2: Project Health Dashboard
A visual KPI table with progress bars and status icons:

```
## Project Health Dashboard

| KPI                  | Current    | Target     | Status | Progress            |
|----------------------|------------|------------|--------|---------------------|
| Master Plan Tasks    | 37/37      | 37         | ✅ DONE | [██████████] 100%  |
| Test Coverage        | 2,400+     | 2,000+     | ✅ MET  | [██████████] 120%  |
| Backend Modules      | 22         | 22         | ✅ DONE | [██████████] 100%  |
| Frontend Components  | 130+       | 100+       | ✅ MET  | [██████████] 130%  |
| Agent Fleet          | 16         | 12+        | ✅ MET  | [██████████] 133%  |
| API Endpoints        | 90+        | 80+        | ✅ MET  | [██████████] 112%  |
| Lint/Type Checks     | Passing    | Passing    | ✅      | [██████████] 100%  |
| Security Issues      | 0 CRITICAL | 0 CRITICAL | ✅ CLEAR| [██████████] 100%  |
```

**Data gathering method:**
- Task counts: `find development/tasks/ -name "*.md" | wc -l` + read task status
- Test counts: `grep -r "def test_\|async def test_" tests/ agent/tests/ --include="*.py" | wc -l`
- Module counts: `find src/ -maxdepth 1 -type d | wc -l`
- Component counts: `find Frontend/src/components -name "*.tsx" | wc -l`
- Agent count: `find .claude/agents -name "*.md" -not -name "CLAUDE.md" | wc -l`
- API endpoints: `grep -r "@router\." src/api/routes/ --include="*.py" | wc -l`
- Lint: `ruff check src/ --quiet 2>&1 | tail -1`
- Security: read latest security review from `development/code-reviews/`

### Section 3: Architecture Overview
- System architecture summary (from root CLAUDE.md)
- Core components table (14 components with status)
- Dependency direction diagram (ASCII)
- Key data flows (price ingestion, order execution, backtesting)
- Technology stack table

### Section 4: Progress & Milestones
- Master plan phase completion status (6 phases with progress bars)
- Recent achievements (from daily notes + git log)
- Feature delivery timeline (commits over time)
- Task board summary (11 boards with completion %)

```
## Phase Completion

Phase 0: Foundation       [██████████] 100% ✅ COMPLETE
Phase 1: Training         [██████████] 100% ✅ COMPLETE
Phase 2: Risk Hardening   [██████████] 100% ✅ COMPLETE
Phase 3: Intelligence     [██████████] 100% ✅ COMPLETE
Phase 4: Continuous Learn  [██████████] 100% ✅ COMPLETE
Phase 5: Platform Improve [██████████] 100% ✅ COMPLETE
Phase 6: Production       [████░░░░░░]  40% 🔄 IN PROGRESS
```

### Section 5: Code Quality & Testing
- Test inventory breakdown (unit, integration, agent, frontend)
- Lint and type-check status
- Code review verdict history (from code-review reports)
- Recent review findings summary
- Quality trend (if multiple reports exist)

### Section 6: Agent Team Status
- Agent fleet inventory (16 agents with roles)
- Agent pipeline descriptions
- Recent agent activity (from activity log)
- Agent memory insights (key learnings)
- Agent improvement recommendations

### Section 7: Trading System Status
- Strategy inventory (5 strategies: RL, evolutionary, regime, risk, ensemble)
- Trading goals vs current capability
- Gymnasium environment status (7 envs, 6 rewards)
- Backtesting engine status
- Battle system status

### Section 8: Risk Assessment
- Security posture (from security reviews)
- Performance risks (from perf-checker findings)
- Technical debt inventory
- Infrastructure risks
- Dependency risks
- Risk matrix table:

```
| Risk                    | Severity | Likelihood | Mitigation              | Owner     |
|-------------------------|----------|------------|-------------------------|-----------|
| Agent isolation bypass  | HIGH     | LOW        | Permission enforcer     | security  |
| N+1 query in portfolio  | MEDIUM   | MEDIUM     | Index optimization      | perf      |
| Stale test assertions   | LOW      | MEDIUM     | Automated test refresh  | test-runner|
```

### Section 9: Infrastructure & Operations
- Docker service inventory (8 services)
- Monitoring stack (Grafana dashboards, Prometheus alerts)
- CI/CD pipeline status
- Environment configuration summary

### Section 10: Strategic Roadmap
- Near-term priorities (next 7-14 days)
- Medium-term goals (next 30-60 days)
- Long-term vision (Q2-Q3 2026)
- Resource requirements
- Key decision points ahead

### Section 11: Recommendations
- Top 5 actionable recommendations (prioritized)
- Resource allocation suggestions
- Risk mitigation steps
- Strategic opportunities

---

## Implementation Plan

### Step 1: Create Skill Directory & Template Files

**Files to create:**

1. `.claude/skills/c-level-report/SKILL.md` — Main skill definition
2. `.claude/skills/c-level-report/templates/report-template.md` — Report skeleton
3. `.claude/skills/c-level-report/examples/sample-report.md` — Example output

**Effort:** ~1 hour

### Step 2: Write SKILL.md Workflow

The SKILL.md must instruct Claude to:

1. **Gather live metrics** — Use bash commands to collect:
   - Git stats (`git log --oneline --since="30 days ago" | wc -l`)
   - Test counts (`grep -r "def test_" tests/ agent/tests/ | wc -l`)
   - File counts for modules, components, agents
   - Lint/type status (`ruff check src/ --quiet`, `mypy src/ --no-error-summary`)
   - Docker service count
   - API endpoint count

2. **Read context files** — Load:
   - `development/context.md` (first 200 lines for current state)
   - `development/trading-agent-master-plan.md` (phase status sections)
   - Latest 2-3 code review reports from `development/code-reviews/`
   - Latest daily note from `development/daily/`
   - Agent memory files from `.claude/agent-memory/*/MEMORY.md`

3. **Analyze and synthesize** — Claude processes all data and generates:
   - KPI calculations with progress bars
   - Phase completion percentages
   - Risk assessment from security/perf findings
   - Trend analysis (if previous reports exist in `development/C-level_reports/`)
   - Actionable recommendations

4. **Generate report** — Output as rich markdown with:
   - ASCII progress bars: `[████████░░] 80%`
   - Status indicators: ✅ ⚠️ ❌ 🔄
   - Formatted tables with aligned columns
   - Section headers with clear hierarchy
   - Frontmatter for Obsidian integration

5. **Save to file** — Write to `development/C-level_reports/report-YYYY-MM-DD.md`

6. **Display summary** — Show key highlights in terminal

**Effort:** ~2 hours

### Step 3: Create Report Template

The template provides consistent structure across reports:

```markdown
---
type: c-level-report
date: {DATE}
scope: {SCOPE}
generated-by: c-level-report-skill
tags:
  - executive
  - status-report
---

# Executive Report — AI Trading Agent Platform

**Date:** {DATE}
**Period:** {PERIOD}
**Scope:** {SCOPE}

---

## Executive Summary
{auto-generated}

## Project Health Dashboard
{KPI table with progress bars}

... (all 11 sections)
```

**Effort:** ~30 minutes

### Step 4: Create Sample Report

A complete example report showing the expected output quality. This helps Claude understand the tone, detail level, and formatting expected.

**Effort:** ~30 minutes

### Step 5: Update CLAUDE.md Navigation

- Add skill to root `CLAUDE.md` skills table
- Add skill to `.claude/skills/CLAUDE.md` inventory
- Create `development/C-level_reports/` directory

**Effort:** ~15 minutes

### Step 6: Test & Iterate

- Run `/c-level-report` and verify output quality
- Check that all data sources are correctly read
- Verify file is saved correctly with proper frontmatter
- Test scoped reports (`/c-level-report agents`, `/c-level-report risk`)
- Refine prompts based on output quality

**Effort:** ~30 minutes

---

## Technical Decisions

### Why `allowed-tools: Read, Write, Grep, Glob, Bash`?

| Tool | Reason |
|------|--------|
| `Read` | Load context.md, master-plan, code reviews, agent memory, daily notes |
| `Write` | Save report to `development/C-level_reports/report-YYYY-MM-DD.md` |
| `Grep` | Count test functions, find API endpoints, search for patterns |
| `Glob` | Find files by pattern (task boards, components, agents, test files) |
| `Bash` | Run git commands, ruff/mypy checks, file counting, date operations |

### Why NOT use `Agent` tool?

The skill gathers data directly rather than delegating to sub-agents. This keeps execution fast (single pass) and avoids the overhead of spawning multiple agents for what is essentially a read-and-synthesize task.

### Why `model: sonnet` (not `opus`)?

The report is data-driven synthesis, not architectural planning. Sonnet handles this well and is faster/cheaper. If report quality is insufficient, we can upgrade to opus later.

### Scoping Strategy

The `$ARGUMENTS` parameter supports focused reports:

| Scope | Sections Included |
|-------|-------------------|
| `full` (default) | All 11 sections |
| `progress` | Sections 1, 2, 4, 10 (health + milestones + roadmap) |
| `quality` | Sections 1, 2, 5, 8 (health + testing + risk) |
| `risk` | Sections 1, 2, 8, 9, 11 (health + risk + infra + recommendations) |
| `agents` | Sections 1, 2, 6, 7 (health + agent team + trading system) |
| `roadmap` | Sections 1, 2, 4, 10, 11 (health + progress + roadmap + recommendations) |

### Trend Analysis (Future Enhancement)

When previous reports exist in `development/C-level_reports/`, the skill can:
- Compare current KPIs to the last report
- Show delta arrows (↑ ↓ →)
- Calculate velocity trends
- Flag regressions

This is a v2 enhancement — v1 generates standalone reports.

---

## Success Criteria

| Criteria | Measurement |
|----------|-------------|
| Report is comprehensive | Covers all 11 sections with real data |
| Metrics are accurate | Numbers match actual git/test/file counts |
| Report is executive-readable | Non-technical reader understands project status in 5 minutes |
| Progress bars render correctly | ASCII art displays properly in markdown viewers |
| File saves correctly | Report appears in `development/C-level_reports/` with frontmatter |
| Scoped reports work | `/c-level-report risk` produces focused risk report |
| Execution time reasonable | Completes in under 3 minutes |

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `context.md` is too large to read fully | Missing context | Read first 200 lines (summary section) + targeted grep for specific data |
| Git history is shallow | Inaccurate velocity | Use `--since` date ranges rather than commit counts |
| Test count changes between runs | Inconsistent metrics | Always count at runtime, never cache |
| Report becomes stale quickly | Misleading data | On-demand execution ensures freshness; add generation timestamp |
| Bash commands fail on Windows | Skill breaks | Use Git Bash compatible commands (already the shell in this environment) |

---

## Execution Order

```
Step 1: Create directory structure          → 15 min
Step 2: Write SKILL.md (core workflow)      → 2 hours
Step 3: Create report template              → 30 min
Step 4: Create sample report                → 30 min
Step 5: Update CLAUDE.md navigation files   → 15 min
Step 6: Test and iterate                    → 30 min
                                        ─────────────
                                Total:    ~4 hours
```

**Dependencies:** None — this skill only reads existing project data.

**Assignable to:** `backend-developer` agent (skill creation is a code/config task)

---

## Next Steps

After this plan is approved:
1. Run `/plan-to-tasks development/c-level-report-skill-plan.md` to create task files, OR
2. Implement directly by creating the 3 files in `.claude/skills/c-level-report/`
3. Test with `/c-level-report` and iterate on output quality
