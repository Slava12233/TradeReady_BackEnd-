---
paths:
  - "development/**/*.md"
  - "development/**/*.yaml"
---

# Obsidian Knowledge Vault

The `development/` directory is an Obsidian vault. Agents and humans share this space.

## Vault Structure

```
development/
  .obsidian/          ← Config (Dataview, Templater, Git plugins)
  _moc/               ← Map of Content hubs (Home.md = entry point)
  _templates/         ← Templater templates (code-review, task, daily-note, plan, research-report)
  _dashboards/        ← Dataview dashboards (project-health, agent-activity)
  _attachments/       ← Images/files
  daily/              ← Daily dev log (YYYY-MM-DD.md, shared human+agent)
  code-reviews/       ← Agent code review reports
  tasks/              ← Task boards
  context.md          ← Rolling dev context (agent-owned)
```

## Frontmatter Convention

All files in `development/` need YAML frontmatter:

```yaml
---
type: code-review | task | task-board | plan | research-report | daily-note | context-log | moc | dashboard
tags:
  - relevant-tags
---
```

## Wikilink Rules

- **Use `[[wikilinks]]` only in `development/` files**
- **NEVER add wikilinks to CLAUDE.md files** — use standard markdown
- **NEVER add wikilinks to source code** — use inline code: `` `src/path/file.py` ``

## File Ownership

| Files | Owner | Rule |
|-------|-------|------|
| `daily/*.md` | Shared | Humans: "Human Notes", agents: "Agent Activity" |
| `context.md` | Agent (context-manager) | Humans read only |
| `code-reviews/*.md` | Agent (code-reviewer) | Humans read only |
| `tasks/**/*.md` | Agent (plan-to-tasks) | Humans read only |
| `_moc/*.md`, `_dashboards/*.md` | Human | Agents don't modify |
| Archived planning docs | Frozen | Neither edits |

## Agent Output Format

- **Code reviews**: frontmatter with `type: code-review`, `date`, `reviewer`, `verdict`, `scope`, `tags`
- **Task files**: frontmatter with `type: task`, `board`, `tags`
- **Context-manager**: after updating `context.md`, also append to today's daily note
