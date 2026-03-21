---
task_id: 13
title: "Create code review template"
type: task
agent: backend-developer
phase: 4
depends_on: [12]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - development/_templates/code-review.md
tags:
  - task
  - obsidian
  - templates
  - code-review
---

# Create code review template

## Assigned Agent: `backend-developer`

## Objective

Create `development/_templates/code-review.md` as an Obsidian Templater template that standardizes code review file creation with frontmatter and consistent structure.

## Context

Ensures every new code review has consistent frontmatter for Dataview and consistent structure for agents. The template matches the existing code-review format documented in `development/code-reviews/CLAUDE.md`. The template is opt-in.

## Files to Create

- `development/_templates/code-review.md`

## Template Content

The template should include:
- YAML frontmatter with Templater dynamic fields (`<% tp.date.now("YYYY-MM-DD") %>`)
- `type: code-review`, `date`, `reviewer`, `verdict`, `scope`, `tags` fields
- Standard report sections: Files Reviewed, CLAUDE.md Files Consulted, Critical Issues, Warnings, Suggestions, Passed Checks
- Checklist items for standard checks (naming, dependency direction, error handling, type safety, agent scoping, async patterns, test coverage)

## Acceptance Criteria

- [ ] Template file exists at `development/_templates/code-review.md`
- [ ] YAML frontmatter uses Templater syntax for dynamic date
- [ ] Report structure matches existing code review format
- [ ] Passed Checks section includes standard checklist items

## Estimated Complexity

Low
