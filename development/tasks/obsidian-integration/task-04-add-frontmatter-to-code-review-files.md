---
task_id: 4
title: "Add frontmatter to code review files"
type: task
agent: backend-developer
phase: 2
depends_on: [1]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - development/code-reviews/review_2026-03-18_16-54_gym-mcp-sdk.md
  - development/code-reviews/review_2026-03-18_22-55_str-ui-1-strategy-training.md
  - development/code-reviews/review_2026-03-18_23-15_str-ui-2-integration-polish.md
  - development/code-reviews/review_2026-03-20_11-29_agent-package.md
  - development/code-reviews/frontend-performance-review.md
  - development/code-reviews/security-review-agent-strategies.md
  - development/code-reviews/perf-check-agent-strategies.md
  - development/code-reviews/review_2026-03-20_16-24_frontend-perf-fixes.md
  - development/code-reviews/security-review-permissions.md
tags:
  - task
  - obsidian
  - frontmatter
  - code-review
---

# Add frontmatter to code review files

## Assigned Agent: `backend-developer`

## Objective

Add YAML frontmatter to all 9 existing code review reports in `development/code-reviews/` so they are searchable, filterable, and visible in Dataview queries.

## Context

Dataview queries need frontmatter to aggregate reviews by date, verdict, and scope. The existing report body structure is preserved unchanged.

## Files to Modify

All 9 review `.md` files (excluding CLAUDE.md):
- `review_2026-03-18_16-54_gym-mcp-sdk.md`
- `review_2026-03-18_22-55_str-ui-1-strategy-training.md`
- `review_2026-03-18_23-15_str-ui-2-integration-polish.md`
- `review_2026-03-20_11-29_agent-package.md`
- `frontend-performance-review.md`
- `security-review-agent-strategies.md`
- `perf-check-agent-strategies.md`
- `review_2026-03-20_16-24_frontend-perf-fixes.md`
- `security-review-permissions.md`

## Frontmatter Format

```yaml
---
type: code-review
date: 2026-03-20
reviewer: code-reviewer
verdict: NEEDS FIXES
scope: frontend-perf-fixes
tags:
  - review
  - frontend
  - performance
---
```

## Extraction Rules

- `date`: from filename pattern `review_YYYY-MM-DD_HH-MM_...` or from `Date:` line in report body
- `reviewer`: from `Reviewer:` line in report body (always `code-reviewer agent` for standard reviews; may be `security-reviewer`, `perf-checker`)
- `verdict`: from `Verdict:` line (`PASS`, `PASS WITH WARNINGS`, `NEEDS FIXES`)
- `scope`: from filename suffix or first heading
- `tags`: inferred from scope keywords and files reviewed

## Acceptance Criteria

- [ ] All 9 review files have valid YAML frontmatter
- [ ] Frontmatter fields (`type`, `date`, `reviewer`, `verdict`, `scope`, `tags`) are populated correctly
- [ ] Existing report body content is preserved unchanged
- [ ] CLAUDE.md in code-reviews/ is NOT modified

## Estimated Complexity

Medium (9 files, each needs manual frontmatter extraction)
