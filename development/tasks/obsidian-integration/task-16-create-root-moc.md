---
task_id: 16
title: "Create root MOC (vault home page)"
type: task
agent: backend-developer
phase: 5
depends_on: [4, 5, 6, 7, 8]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - development/_moc/Home.md
tags:
  - task
  - obsidian
  - moc
  - navigation
---

# Create root MOC (vault home page)

## Assigned Agent: `backend-developer`

## Objective

Create `development/_moc/Home.md` as the vault landing page with quick links, platform status, and vault structure overview.

## Context

A home page gives humans a starting point. Graph view centers on this node. It links to all topic MOCs, context, and key vault areas.

## Files to Create

- `development/_moc/Home.md`

## Content Requirements

- Frontmatter: `type: moc`, `title`, `aliases: [home, index]`, `tags: [moc]`
- Quick Links section with wikilinks to: `[[context]]`, `[[daily-log-moc]]`, `[[task-boards-moc]]`, `[[code-reviews-moc]]`, `[[plans-moc]]`, `[[research-moc]]`, `[[wikilink-conventions]]`
- Active Work section linking to `[[context#Current State]]`
- Platform Status table (Backend, Frontend, Agent Fleet, Documentation)
- Vault Structure ASCII tree showing directory layout

## Acceptance Criteria

- [ ] `development/_moc/Home.md` exists with valid frontmatter
- [ ] Aliases include `home` and `index`
- [ ] Quick Links section has wikilinks to all topic MOCs
- [ ] Vault structure overview matches actual directory layout

## Estimated Complexity

Low
