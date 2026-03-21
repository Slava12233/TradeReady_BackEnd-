---
task_id: 14
title: "Create task file template"
type: task
agent: backend-developer
phase: 4
depends_on: [12]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - development/_templates/task.md
tags:
  - task
  - obsidian
  - templates
---

# Create task file template

## Assigned Agent: `backend-developer`

## Objective

Create `development/_templates/task.md` as an Obsidian Templater template that matches the existing task file YAML frontmatter format used by `/plan-to-tasks` skill, with added Obsidian-compatible fields.

## Context

Matches the existing task file YAML frontmatter format used by `/plan-to-tasks` skill, with added Obsidian-compatible fields (`type`, `board`, `tags`). Template preserves all existing frontmatter fields agents rely on.

## Files to Create

- `development/_templates/task.md`

## Template Content

The template should include:
- YAML frontmatter with: `task_id`, `title` (Templater dynamic), `type: task`, `agent`, `phase`, `depends_on`, `status: pending`, `priority`, `board`, `files`, `tags`
- Sections: Assigned Agent, Objective, Context, Files to Modify, Acceptance Criteria, Agent Instructions, Estimated Complexity
- Templater cursor placement (`<% tp.file.cursor() %>`) in Objective section

## Acceptance Criteria

- [ ] Template file exists at `development/_templates/task.md`
- [ ] YAML frontmatter includes all fields used by `/plan-to-tasks` skill
- [ ] Added `type: task`, `board`, and `tags` fields for Obsidian compatibility
- [ ] Template uses Templater syntax for dynamic title

## Estimated Complexity

Low
