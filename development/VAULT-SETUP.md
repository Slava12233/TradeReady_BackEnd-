---
type: guide
title: Obsidian Vault Setup
tags:
  - guide
  - obsidian
---

# Obsidian Vault Setup

One-time setup to use the `development/` directory as an Obsidian vault.

## Prerequisites

- [Obsidian](https://obsidian.md/) installed (free, available on Windows/Mac/Linux)

## Steps

### 1. Open the Vault

1. Open Obsidian
2. Click "Open folder as vault"
3. Navigate to `<repo-root>/development/`
4. Click "Open"

### 2. Install Community Plugins

The vault config already lists required plugins, but you need to install the binaries:

1. Go to **Settings > Community Plugins**
2. Click **"Turn on community plugins"** if prompted
3. Click **Browse** and install these 3 plugins:
   - **Dataview** — by Michael Brenan (data queries and dashboards)
   - **Templater** — by SilentVoid (template engine for new files)
   - **Git** — by Vinzent (auto-pull agent changes, manual commit)
4. Enable all 3 plugins after installation

### 3. Verify Setup

- [ ] Open `_moc/Home.md` — should show the vault home page
- [ ] Open `_dashboards/project-health.md` — Dataview tables should render
- [ ] Graph view (`Ctrl+G`) shows connected nodes with color coding
- [ ] Create a new note with Templater (`Ctrl+N`) — templates should be available
- [ ] Git status bar shows at the bottom of the window

### 4. Set Home Page (Optional)

1. Install the **Homepage** community plugin
2. Set `_moc/Home` as the homepage
3. Now opening the vault always starts at the home page

## Graph Color Legend

| Color | Content |
|-------|---------|
| Blue | Tasks |
| Red | Code Reviews |
| Green | Plans |
| Yellow | Daily Notes |
| Purple | MOC (Map of Content) |

## Troubleshooting

**Dataview tables show "No results"**
- Ensure Dataview plugin is enabled
- Check that files have YAML frontmatter with `type:` field

**Templates not appearing**
- Ensure Templater plugin is enabled
- Check Settings > Templater > Template folder is set to `_templates`

**Git not syncing**
- Ensure Git plugin is enabled
- The repo must be a git repo (it is)
- Check Settings > Git > Auto pull interval is 10

## File Structure

```
development/                  ← This is your vault root
  .obsidian/                  ← Vault config (auto-loaded)
  _moc/                       ← Navigation hub notes
    Home.md                   ← Start here
  _templates/                 ← File templates
  _dashboards/                ← Dataview dashboards
  _attachments/               ← Image/file attachments
  daily/                      ← Daily development log
  code-reviews/               ← Agent code review reports
  tasks/                      ← Task boards (8 boards)
  context.md                  ← Rolling dev context (agent-maintained)
  ...                         ← Planning docs, research reports
```
