---
task_id: 2
title: "Create report template for consistent structure"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "medium"
board: "[[c-level-report-skill/README]]"
files:
  - ".claude/skills/c-level-report/templates/report-template.md"
tags:
  - task
  - skill
  - template
---

# Task 2: Create Report Template

## Assigned Agent: `backend-developer`

## Objective

Create a report skeleton at `.claude/skills/c-level-report/templates/report-template.md` that defines the consistent markdown structure for every generated report. This template is referenced by SKILL.md during report generation.

## Context

The template ensures consistent formatting across all reports. Claude uses it as a structural reference — not a direct copy-paste, but as a guide for section ordering, table formats, and visual element patterns.

## Files to Create

- `.claude/skills/c-level-report/templates/report-template.md` — Report skeleton

## Template Contents

### Frontmatter Template

```yaml
---
type: c-level-report
date: {YYYY-MM-DD}
scope: {full|progress|quality|risk|agents|roadmap}
generated-by: c-level-report-skill
platform: AI Trading Agent
version: "1.0"
tags:
  - executive
  - status-report
---
```

### Section Templates (all 11)

For each section, include:
- H2 heading with section number
- Brief comment describing what data sources to use
- Pre-formatted table structure (columns, alignments)
- Placeholder markers like `{METRIC_VALUE}`, `{PROGRESS_BAR}`, `{STATUS_ICON}`

### Visual Elements Reference Section

Document the exact formatting patterns:

```markdown
## Visual Elements Reference

### Progress Bars (10-character width)
- 100%: [██████████] 100%
-  80%: [████████░░]  80%
-  60%: [██████░░░░]  60%
-  40%: [████░░░░░░]  40%
-  20%: [██░░░░░░░░]  20%
-   0%: [░░░░░░░░░░]   0%

### Status Icons
- ✅ On track / Met / Complete / Clear
- ⚠️ At risk / Warning / Needs attention
- ❌ Critical / Missed / Failed
- 🔄 In progress / Active / Monitoring

### Trend Arrows (for comparisons with previous reports)
- ↑ Improved (green context)
- ↓ Declined (red context)
- → Stable (neutral context)
```

### Footer Template

```markdown
---

**Generated:** {YYYY-MM-DD HH:MM UTC}
**Scope:** {SCOPE}
**Data sources:** context.md, master-plan, git log, test inventory, code reviews, agent memory
**Next recommended report:** {DATE + 7 days}
```

## Acceptance Criteria

- [ ] File exists at `.claude/skills/c-level-report/templates/report-template.md`
- [ ] All 11 section headers present with placeholder structure
- [ ] Table templates have proper markdown alignment
- [ ] Visual elements reference section included
- [ ] Frontmatter template with all required fields
- [ ] Footer template included

## Estimated Complexity

**Medium** — Structured markdown authoring, no code logic.
