---
type: moc
title: Git Workflow
tags:
  - moc
  - git
  - workflow
---

# Git Workflow for the Development Vault

## How It Works

```
┌─────────────┐          ┌──────────────┐
│  Obsidian   │  ←────→  │  Claude Code  │
│  (Human)    │          │  (AI Agents)  │
├─────────────┤          ├──────────────┤
│ Write plans │ ───────→ │ Read plans    │
│ Review PRs  │ ───────→ │ Execute tasks │
│ Add context │ ───────→ │ Use as input  │
│ Read reports│ ←─────── │ Write reports │
│ Track graph │ ←─────── │ Update links  │
└─────────────┘          └──────────────┘
```

## Obsidian Git Plugin

- **Auto-pull:** Every 10 minutes (picks up agent changes)
- **Auto-pull on boot:** Enabled (always start with latest)
- **Auto-save:** Disabled (humans commit manually)
- **Commit format:** `docs(vault): auto-sync {{date}}`
- **Sync method:** Merge (not rebase)

## Manual Commit from Obsidian

1. Open the command palette (`Ctrl+P`)
2. Search "Git: Commit all changes"
3. Or use the sidebar Git panel (`Ctrl+Shift+G`)

## File Ownership

| Files | Owner | Who Edits |
|-------|-------|-----------|
| `daily/*.md` | Shared | Humans write "Human Notes", agents append "Agent Activity" |
| `context.md` | Agent (context-manager) | Humans read only |
| `code-reviews/*.md` | Agent (code-reviewer) | Humans read only |
| `tasks/**/*.md` | Agent (various) | Humans read only |
| `_moc/*.md` | Human | Humans edit, agents don't touch |
| `_dashboards/*.md` | Human | Humans edit, agents don't touch |
| Planning docs (`*.md` root) | Frozen/archived | Neither edits |

## Conflict Resolution

1. **Most files are append-only** — conflicts are rare
2. If a conflict occurs, git shows standard conflict markers
3. Resolve in any editor, then commit the merge
4. Rule of thumb: if in doubt, keep the agent's version (it's usually the newer data)

## Tips

- **Pull before editing** — click "Pull" in the Obsidian Git sidebar before writing
- **Don't edit `context.md`** — write in daily notes instead; the context-manager will incorporate it
- **Commit message convention** — use `docs(vault): description` for vault-only changes
