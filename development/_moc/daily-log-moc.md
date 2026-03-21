---
type: moc
title: Daily Development Log
tags:
  - moc
  - daily
---

# Daily Development Log

## How to Use Daily Notes

1. **Create a note**: In Obsidian, use Templater (`Ctrl+N` > select `daily-note` template) or the Daily Notes plugin
2. **Human Notes section**: Write your observations, decisions, blockers, and plans
3. **Agent Activity section**: Agents auto-populate this after each task via the context-manager
4. **Navigation**: Each note links to previous/next day and to [[context]]

## Relationship to context.md

- `[[context]]` is the **canonical record** — maintained by the context-manager agent
- Daily notes are the **working scratchpad** — where humans and agents log activity in real-time
- Think of daily notes as the raw journal; context.md as the curated summary

## Dataview: Recent Daily Notes

```dataview
TABLE date
FROM ""
WHERE type = "daily-note"
SORT date DESC
LIMIT 14
```

## All Daily Notes

```dataview
LIST
FROM ""
WHERE type = "daily-note"
SORT date DESC
```
