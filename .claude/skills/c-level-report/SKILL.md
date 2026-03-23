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

# C-Level Executive Report Generator

Generate a professional C-level executive report with real-time metrics, progress tracking, risk assessment, and strategic recommendations.

## Scope Handling

Check `$ARGUMENTS` for report scope:
- `full` or empty → generate all 11 sections
- `progress` → sections 1, 2, 4, 10 only
- `quality` → sections 1, 2, 5, 8 only
- `risk` → sections 1, 2, 8, 9, 11 only
- `agents` → sections 1, 2, 6, 7 only
- `roadmap` → sections 1, 2, 4, 10, 11 only

## Step 1: Gather Live Metrics

Run these bash commands to collect real-time project data:

```bash
# Git activity
git log --oneline --since="30 days ago" | wc -l
git log --oneline -10
git shortlog -sn --since="30 days ago"

# Test inventory
grep -r "def test_\|async def test_" tests/ agent/tests/ --include="*.py" | wc -l
find Frontend/src -name "*.test.*" -o -name "*.spec.*" | wc -l

# Codebase metrics
find src/ -maxdepth 1 -type d | wc -l
find Frontend/src/components -name "*.tsx" | wc -l
find .claude/agents -name "*.md" -not -name "CLAUDE.md" | wc -l
grep -r "@router\." src/api/routes/ --include="*.py" | wc -l

# Infrastructure
find development/tasks -maxdepth 1 -type d | wc -l
wc -l development/agent-activity-log.jsonl 2>/dev/null || echo "0"
find monitoring/provisioning -name "*.json" 2>/dev/null | wc -l
docker compose config --services 2>/dev/null | wc -l || echo "8"
```

## Step 2: Read Context Files

Read these files to understand current project state:

1. **Project state:** `development/context.md` (first 150 lines — overview table and current state)
2. **Master plan:** `development/trading-agent-master-plan.md` (first 100 lines — executive summary, phases, success metrics)
3. **Code reviews:** Glob `development/code-reviews/*.md`, read the 2 most recent files (sorted by filename)
4. **Daily notes:** Glob `development/daily/*.md`, read the most recent file
5. **Agent memory (security):** `.claude/agent-memory/security-reviewer/MEMORY.md`
6. **Agent memory (perf):** `.claude/agent-memory/perf-checker/MEMORY.md`
7. **Agent memory (code quality):** `.claude/agent-memory/code-reviewer/MEMORY.md`

## Step 3: Check for Previous Reports

Glob `development/C-level_reports/report-*.md`. If previous reports exist:
- Read the most recent one
- Compare key KPIs to current values
- Show trends: ↑ improved, ↓ declined, → stable

If no previous reports exist, skip the trend comparison.

## Step 4: Generate Report

Generate the report with all applicable sections (based on scope). Use the template in `templates/report-template.md` for structure reference and the example in `examples/sample-report.md` for tone/quality reference.

### Section 1: Executive Summary
- Report date (today), period (last 30 days), scope
- Platform: "AI Trading Agent — simulated crypto exchange where AI agents trade virtual USDT against real Binance market data"
- 3-5 key highlights as bullet points (derived from data gathered)
- Overall health indicator using progress bar format

### Section 2: Project Health Dashboard
KPI table with these rows (adjust based on gathered metrics):

| KPI | Current | Target | Status | Progress |
|-----|---------|--------|--------|----------|
| Master Plan Tasks | {from context.md} | 37 | {icon} | {bar} |
| Test Coverage | {from grep count} | 2,000+ | {icon} | {bar} |
| Backend Modules | {from find count} | 22 | {icon} | {bar} |
| Frontend Components | {from find count} | 100+ | {icon} | {bar} |
| Agent Fleet | {from find count} | 12+ | {icon} | {bar} |
| API Endpoints | {from grep count} | 80+ | {icon} | {bar} |
| Security Issues | {from security memory} | 0 CRITICAL | {icon} | {bar} |

Progress bars use 10-char format: `[████████░░] 80%`

### Section 3: Architecture Overview
- 14 core components table (from root CLAUDE.md architecture section)
- Technology stack: Python 3.12, FastAPI, TimescaleDB, Redis, Next.js 16, React 19
- Key data flows: price ingestion, order execution, backtesting (1-2 sentences each)
- Dependency direction: Routes → Schemas + Services → Repositories → Models

### Section 4: Progress & Milestones
- Phase completion bars for all 6 master plan phases
- Recent achievements from git log and daily notes
- Task board summary: list all task boards with completion status

### Section 5: Code Quality & Testing
- Test breakdown: unit ({count}), integration ({count}), agent ({count}), frontend ({count})
- Latest code review verdict and key findings
- Lint status (ruff), type-check status (mypy)

### Section 6: Agent Team Status
- Agent fleet table: Name | Role | Model | Tools | Status
- Agent pipelines: Standard post-change, API/schema, security, perf, migration, feature
- Key learnings from agent memory files (2-3 bullet points)

### Section 7: Trading System Status
- 5 strategies: PPO RL, Evolutionary GA, Regime Detection, Risk Overlay, Ensemble Combiner
- Trading goals: 10% monthly return, Sharpe ≥ 1.5, max drawdown ≤ 8%
- Gymnasium: 7 environments, 6 reward functions (including CompositeReward)
- Battle system status and backtesting engine status

### Section 8: Risk Assessment
Risk matrix table with entries derived from security-reviewer memory, perf-checker memory, and code review findings:

| Risk | Severity | Likelihood | Mitigation | Owner |
|------|----------|------------|------------|-------|

Include categories: security, performance, technical debt, infrastructure, dependency

### Section 9: Infrastructure & Operations
- Docker services (8): PostgreSQL, Redis, Celery worker, Celery beat, API, Frontend, Prometheus, Grafana
- Monitoring: {N} Grafana dashboards, 11 Prometheus alert rules, 16 agent metrics
- CI/CD pipeline status
- Environment configuration summary

### Section 10: Strategic Roadmap
- Near-term (7-14 days): immediate priorities
- Medium-term (30-60 days): upcoming goals
- Long-term (Q2-Q3 2026): vision items
- Key decision points ahead

### Section 11: Recommendations
Top 5 prioritized recommendations, each with:
- **What:** specific action
- **Why:** justification from data
- **Impact:** expected outcome

## Step 5: Save Report

1. Create directory if needed: `mkdir -p development/C-level_reports`
2. Determine filename: `report-YYYY-MM-DD.md` (use today's date)
3. If file exists, use: `report-YYYY-MM-DD-HHMMSS.md`
4. Write report with Obsidian frontmatter:

```yaml
---
type: c-level-report
date: YYYY-MM-DD
scope: {scope}
generated-by: c-level-report-skill
platform: AI Trading Agent
tags:
  - executive
  - status-report
---
```

## Step 6: Display Terminal Summary

After saving, display:
1. File path where report was saved
2. 5-line executive summary (the highlights from Section 1)
3. Top 3 recommendations (from Section 11)
4. If trend data available, show KPI changes since last report

## Rules

1. **All metrics must be gathered at runtime** via Bash/Grep/Glob — never hardcode numbers
2. **Progress bars** use `[████████░░] 80%` format (10-char width, ██ for filled, ░░ for empty)
3. **Status indicators:** ✅ On track/Met, ⚠️ At risk, ❌ Critical/Missed, 🔄 In progress
4. **Tables** must be properly aligned markdown with `|---|` header separators
5. **Timestamps** in both frontmatter AND report body
6. **Never fabricate data** — if a source is unavailable, write "Data unavailable"
7. **Bash commands** must use forward slashes and Git Bash compatible syntax
8. **Tone:** Professional, executive-level. Lead with outcomes, not implementation details. Use specific numbers.
9. **Length:** Full report 250-400 lines. Scoped reports proportionally shorter.
