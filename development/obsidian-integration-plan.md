# Implementation Plan: Obsidian Knowledge Management Integration

## Overview

Turn the `development/` directory into an Obsidian vault that humans can browse with graph view, backlinks, and daily notes, while preserving all existing Claude Code agent workflows. Agent outputs (code reviews, task files, context updates) will gain Obsidian-compatible frontmatter and wikilinks. Dataview queries will power dashboards for task progress, agent activity, and code review trends. The integration is purely additive -- no existing file functionality changes, no agent source code rewrites.

## CLAUDE.md Files Consulted

- Root `CLAUDE.md` -- architecture overview, agent pipelines, sub-agent inventory
- `development/CLAUDE.md` -- file inventory, directory structure, patterns
- `development/code-reviews/CLAUDE.md` -- review naming convention, report structure
- `.claude/agents/CLAUDE.md` -- agent inventory, pipelines, configuration fields
- `.claude/agent-memory/CLAUDE.md` -- memory file format, directory structure
- `.claude/skills/CLAUDE.md` -- skill inventory, review-changes workflow
- `scripts/CLAUDE.md` -- script inventory, agent activity logging scripts
- `.claude/agents/context-manager.md` -- context.md maintenance workflow
- `.claude/agents/doc-updater.md` -- documentation sync workflow
- `.claude/skills/review-changes/SKILL.md` -- post-change pipeline

## Requirements

1. `development/` becomes a valid Obsidian vault (with `.obsidian/` config folder)
2. Humans browse plans, code reviews, tasks, and context using Obsidian graph view and backlinks
3. Bidirectional workflow: humans write in Obsidian, agents read; agents write, humans review in Obsidian
4. Agent output files gain Obsidian-compatible YAML frontmatter and `[[wikilinks]]`
5. Obsidian templates standardize agent output formats
6. Dataview queries provide dashboards (agent activity, task progress, code review trends)
7. CLAUDE.md files coexist with Obsidian without conflict (CLAUDE.md files are NOT part of the vault)
8. Daily development log system for both humans and agents
9. MOC (Map of Content) files for vault navigation
10. Obsidian Git plugin configuration for auto-sync

## Architecture

### Vault Boundary

```
development/              <-- Obsidian vault root
  .obsidian/              <-- Obsidian config (committed to git for team sharing)
    app.json
    appearance.json
    community-plugins.json
    plugins/
      dataview/
      obsidian-git/
      templater-obsidian/
    templates.json
    graph.json
  _templates/             <-- Obsidian Templater templates (underscore prefix = excluded from search)
  _dashboards/            <-- Dataview dashboard notes
  _moc/                   <-- Map of Content index notes
  daily/                  <-- Daily development log notes (YYYY-MM-DD.md)
  context.md              <-- Existing rolling context (gains frontmatter)
  code-reviews/           <-- Existing (reports gain frontmatter + wikilinks)
  tasks/                  <-- Existing task boards (gain frontmatter + wikilinks)
  agent-development/      <-- Existing archived docs (frontmatter only, no other changes)
  ... (all other existing files)
```

### What is NOT in the vault

- CLAUDE.md files throughout the repo (they live in source dirs, not `development/`)
- `.claude/agent-memory/` (separate memory system, not human-browsable docs)
- Source code (`src/`, `agent/`, `Frontend/`, etc.)
- The vault only sees `development/**/*` -- the `.obsidian/` folder at `development/.obsidian/` scopes it

### Coexistence Rules

1. **CLAUDE.md files are untouched.** They use standard markdown without Obsidian features. They remain the agent navigation system.
2. **Obsidian features live only in `development/`.** No wikilinks in source code comments or CLAUDE.md files.
3. **Frontmatter is additive.** Existing task files already use YAML frontmatter (task_id, title, agent, phase, etc.). Obsidian reads the same YAML -- no conflict.
4. **Agent outputs are markdown.** Obsidian reads standard markdown. The only additions are: YAML frontmatter on files that lack it, and optional `[[wikilinks]]` in cross-references.

---

## Implementation Steps

### Phase 1: Vault Foundation (3 tasks)

> Goal: Create the Obsidian vault structure. Open `development/` in Obsidian and see a working graph.

#### Task 01: Create Obsidian vault configuration
- **Agent:** `backend-developer`
- **Phase:** 1
- **Depends on:** None
- **Priority:** High
- **Action:** Create `development/.obsidian/` directory with initial configuration files
- **Files to create:**
  - `development/.obsidian/app.json` -- core Obsidian settings (default new file location: `daily/`, attachment folder: `_attachments/`, strict line breaks off)
  - `development/.obsidian/appearance.json` -- minimal theme config
  - `development/.obsidian/community-plugins.json` -- enable list: `["dataview", "obsidian-git", "templater-obsidian"]`
  - `development/.obsidian/graph.json` -- graph view settings (color groups: tasks=blue, reviews=red, plans=green, daily=yellow, moc=purple)
  - `development/.obsidian/hotkeys.json` -- empty (user customizes)
  - `development/.obsidian/workspace.json` -- default workspace layout
- **Config details for `app.json`:**
  ```json
  {
    "newFileLocation": "folder",
    "newFileFolderPath": "daily",
    "attachmentFolderPath": "_attachments",
    "alwaysUpdateLinks": true,
    "strictLineBreaks": false,
    "showFrontmatter": true,
    "readableLineLength": true,
    "showLineNumber": true
  }
  ```
- **Why:** Obsidian needs a `.obsidian/` folder to recognize a directory as a vault. Committing this config to git means every team member gets the same setup when they open the vault.
- **Risk:** Low. Pure file creation; no existing files touched.
- **Estimated complexity:** Low

#### Task 02: Create vault directory structure
- **Agent:** `backend-developer`
- **Phase:** 1
- **Depends on:** Task 01
- **Priority:** High
- **Action:** Create the new directories and placeholder files for the vault structure
- **Files to create:**
  - `development/_templates/.gitkeep`
  - `development/_dashboards/.gitkeep`
  - `development/_moc/.gitkeep`
  - `development/_attachments/.gitkeep`
  - `development/daily/.gitkeep`
- **Why:** Obsidian templates, dashboards, and daily notes need their own folders. The underscore prefix convention keeps internal vault management files out of the way when browsing content.
- **Risk:** Low. Creating empty directories.
- **Estimated complexity:** Low

#### Task 03: Update .gitignore for Obsidian artifacts
- **Agent:** `backend-developer`
- **Phase:** 1
- **Depends on:** Task 01
- **Priority:** High
- **Action:** Add Obsidian-specific gitignore entries to the project `.gitignore`
- **File to modify:** `.gitignore`
- **Entries to add:**
  ```gitignore
  # ─── Obsidian (development vault) ─────────────────────────────────────────
  # Commit .obsidian/ config but exclude workspace state and local plugin caches
  development/.obsidian/workspace.json
  development/.obsidian/workspace-mobile.json
  development/.obsidian/.obsidian-git
  development/.obsidian/plugins/*/data.json
  !development/.obsidian/plugins/dataview/data.json
  ```
- **Why:** `workspace.json` is per-user layout state that creates merge conflicts. Plugin `data.json` files contain local state except for Dataview (whose settings we want shared). The `.obsidian/` folder itself is committed so team members get the same plugin list and graph colors.
- **Risk:** Low. Additive gitignore entries only.
- **Estimated complexity:** Low

---

### Phase 2: Frontmatter Enrichment (5 tasks)

> Goal: Add Obsidian-compatible YAML frontmatter to all existing files in `development/`. This makes them searchable, filterable, and visible in Dataview queries.

#### Task 04: Add frontmatter to code review files
- **Agent:** `backend-developer`
- **Phase:** 2
- **Depends on:** Task 01
- **Priority:** High
- **Action:** Add YAML frontmatter to all existing code review reports in `development/code-reviews/`
- **Files to modify:** All 9 review `.md` files (excluding CLAUDE.md)
  - `review_2026-03-18_16-54_gym-mcp-sdk.md`
  - `review_2026-03-18_22-55_str-ui-1-strategy-training.md`
  - `review_2026-03-18_23-15_str-ui-2-integration-polish.md`
  - `review_2026-03-20_11-29_agent-package.md`
  - `frontend-performance-review.md`
  - `security-review-agent-strategies.md`
  - `perf-check-agent-strategies.md`
  - `review_2026-03-20_16-24_frontend-perf-fixes.md`
  - `security-review-permissions.md`
- **Frontmatter format:**
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
- **Extraction rules:**
  - `date`: from filename pattern `review_YYYY-MM-DD_HH-MM_...` or from `Date:` line in report body
  - `reviewer`: from `Reviewer:` line in report body (always `code-reviewer agent` for standard reviews; may be `security-reviewer`, `perf-checker`)
  - `verdict`: from `Verdict:` line (`PASS`, `PASS WITH WARNINGS`, `NEEDS FIXES`)
  - `scope`: from filename suffix or first heading
  - `tags`: inferred from scope keywords and files reviewed
- **Why:** Dataview queries need frontmatter to aggregate reviews by date, verdict, and scope. The existing report body structure is preserved unchanged.
- **Risk:** Low. Adding content before existing content. Reports are append-only per CLAUDE.md rules.
- **Estimated complexity:** Medium (9 files, each needs manual frontmatter extraction)

#### Task 05: Add frontmatter to task board READMEs
- **Agent:** `backend-developer`
- **Phase:** 2
- **Depends on:** Task 01
- **Priority:** High
- **Action:** Add YAML frontmatter to all task board README.md files
- **Files to modify:**
  - `development/tasks/tradeready-test-agent/README.md`
  - `development/tasks/agent-strategies/README.md`
  - `development/tasks/frontend-performance-fixes/README.md`
  - `development/tasks/agent-deployment-training/README.md`
  - `development/tasks/agent-ecosystem/README.md`
  - `development/tasks/agent-memory-system/README.md`
- **Frontmatter format:**
  ```yaml
  ---
  type: task-board
  title: Agent Memory & Learning System
  created: 2026-03-21
  status: done
  total_tasks: 14
  plan_source: "[[agent-memory-strategy-report]]"
  tags:
    - task-board
    - agent-memory
  ---
  ```
- **Why:** Enables Dataview to list all task boards, filter by status (done/in-progress), and count total tasks across the project.
- **Risk:** Low. Adding frontmatter before existing content.
- **Estimated complexity:** Low (6 files, simple metadata)

#### Task 06: Add frontmatter to individual task files
- **Agent:** `backend-developer`
- **Phase:** 2
- **Depends on:** Task 05
- **Priority:** Medium
- **Action:** Verify and normalize YAML frontmatter on all individual task files. Most task files already have YAML frontmatter (task_id, title, agent, phase, depends_on, status, priority, files). Add `type: task` and `tags` fields to existing frontmatter. Add `board` field pointing to the parent board.
- **Scope:** All ~110 task files across 6 task board directories
- **Fields to add to existing frontmatter:**
  ```yaml
  type: task
  board: "[[agent-memory-system/README]]"
  tags:
    - task
    - agent-memory
  ```
- **Why:** The `type` and `board` fields enable Dataview to query tasks globally across all boards. The `tags` field enables tag-based navigation.
- **Risk:** Medium. Must not corrupt existing YAML frontmatter that agents depend on (task_id, status, depends_on). The `status` field is read by the `/plan-to-tasks` skill.
- **Estimated complexity:** High (110+ files, but each change is small and mechanical)

#### Task 07: Add frontmatter to planning docs and research reports
- **Agent:** `backend-developer`
- **Phase:** 2
- **Depends on:** Task 01
- **Priority:** Medium
- **Action:** Add YAML frontmatter to the ~28 standalone planning docs and research reports in `development/`
- **Files to modify:** All `.md` files in `development/` root that lack frontmatter:
  - `developmantPlan.md`, `developmentprogress.md`, `tasks.md`
  - `codereviewplan.md`, `codereviewtasks.md`
  - `agentic-layer-plan-tasks.md`
  - `agents-backtesting-battles-research.md`
  - `backtesting_tasks.md`, `backtestingdevelopment.md`
  - `multiagent_battle_tasks.md`, `multiagent_fix_tasks.md`, `Multiagentbattleplan.md`
  - `integration_tasks.md`, `test_coverage_tasks.md`
  - `gap_fill_implementation_plan.md`, `market_data_gap_fill.md`
  - `platform-tools-report.md`, `agent-trading-strategy-report.md`, `data-pipeline-report.md`
  - `plan.md`, `executive-summary.md`, `agent-ecosystem-plan.md`
  - `agent-memory-strategy-report.md`
  - `agent-logging-research.md`, `agent-logging-plan.md`
  - `docs-plan-task.md`
  - Subdirectory docs: `agent-development/agent_plan.md`, `agent-development/tasks.md`, `agent-development/agent-strategies-report.md`, `agent-development/agent-strategies-cto-brief.md`, `agent-development/battle-historical-investigation.md`
  - `ccxt/` directory docs
  - `Gym_api/` directory docs
  - `docs-development/` directory docs
- **Frontmatter format (varies by type):**
  ```yaml
  ---
  type: plan          # or: research-report, task-list, investigation
  title: Agent Ecosystem Plan
  created: 2026-03-20
  status: archived    # or: active, complete
  phase: agent-ecosystem
  tags:
    - plan
    - agent-ecosystem
  ---
  ```
- **Type mapping rules:**
  - Files ending in `plan.md` or `Plan.md` -> `type: plan`
  - Files ending in `tasks.md` -> `type: task-list`
  - Files ending in `report.md` or `research.md` -> `type: research-report`
  - Files with `investigation` in name -> `type: investigation`
  - `executive-summary.md` -> `type: executive-summary`
  - `developmentprogress.md` -> `type: progress-tracker`
- **Why:** Makes all planning docs discoverable through Dataview. Tags enable cross-referencing (e.g., all docs related to "battles").
- **Risk:** Low. These files are archived and frozen per development/CLAUDE.md rules. Adding frontmatter does not modify their content.
- **Estimated complexity:** High (30+ files, but mechanical)

#### Task 08: Add frontmatter to context.md
- **Agent:** `backend-developer`
- **Phase:** 2
- **Depends on:** Task 01
- **Priority:** High
- **Action:** Add YAML frontmatter to `development/context.md` -- the only actively maintained file in the vault
- **Frontmatter to add:**
  ```yaml
  ---
  type: context-log
  title: Development Context Log
  maintained_by: context-manager
  aliases:
    - context
    - dev log
    - development log
  tags:
    - context
    - active
  ---
  ```
- **Critical consideration:** The context-manager agent writes to this file after every task. The agent must be instructed to preserve the frontmatter block when it edits. Current workflow reads the file first (Step 1 of its workflow), then edits specific sections. Since it uses the `Edit` tool (not `Write`), frontmatter is safe -- `Edit` only replaces matched strings.
- **Why:** Enables `[[context]]` alias links from anywhere in the vault. The frontmatter is read-only metadata that the Edit tool won't touch.
- **Risk:** Low. The context-manager agent uses string-match editing, not full file rewrites. Frontmatter block at the top will never match an edit target.
- **Estimated complexity:** Low

---

### Phase 3: Wikilinks and Cross-References (3 tasks)

> Goal: Add `[[wikilinks]]` to agent output files so Obsidian builds a connected graph. Wikilinks are only added in `development/` files -- never in CLAUDE.md or source code.

#### Task 09: Define wikilink convention and reference map
- **Agent:** `backend-developer`
- **Phase:** 3
- **Depends on:** Phase 2
- **Priority:** High
- **Action:** Create `development/_moc/wikilink-conventions.md` documenting the project's wikilink standards
- **Content of the conventions file:**
  - **Link targets:** Use file name without extension (e.g., `[[context]]`, `[[agent-ecosystem-plan]]`)
  - **Task links:** `[[agent-memory-system/task-01-enable-memory-all-agents|Task 01]]` (folder-scoped to avoid collisions)
  - **Review links:** `[[review_2026-03-20_16-24_frontend-perf-fixes|Frontend Perf Review]]` (pipe alias for readability)
  - **Board links:** `[[agent-memory-system/README|Agent Memory Board]]`
  - **External code links:** Use inline code, not wikilinks: `src/agents/service.py` (no link -- source files are outside the vault)
  - **Section links:** `[[context#Current State]]` for linking to specific headings
  - **Tag conventions:** Prefix with category: `review/security`, `task/agent-memory`, `plan/battles`
- **Why:** Without consistent conventions, wikilinks will diverge between human-written and agent-written notes. A conventions file serves as reference for both.
- **Risk:** Low. Documentation only.
- **Estimated complexity:** Low

#### Task 10: Add wikilinks to task board READMEs
- **Agent:** `backend-developer`
- **Phase:** 3
- **Depends on:** Tasks 05, 09
- **Priority:** Medium
- **Action:** Add `[[wikilinks]]` to cross-references within task board README files
- **Link targets to add:**
  - Plan source references: `development/agent-memory-strategy-report.md` becomes `[[agent-memory-strategy-report]]`
  - Agent references in task tables: `context-manager` becomes `context-manager` (no link -- agents are outside vault)
  - Inter-board references where they exist
  - Link to `[[context]]` where the boards reference development/context.md
- **Example transformation in agent-memory-system/README.md:**
  ```markdown
  # Before
  **Plan source:** `development/agent-memory-strategy-report.md`

  # After
  **Plan source:** [[agent-memory-strategy-report]]
  ```
- **Why:** Creates graph connections between plans and their task boards.
- **Risk:** Low. Additive text changes in non-agent-parsed sections of READMEs.
- **Estimated complexity:** Low (6 files)

#### Task 11: Add wikilinks to code review reports
- **Agent:** `backend-developer`
- **Phase:** 3
- **Depends on:** Tasks 04, 09
- **Priority:** Medium
- **Action:** Add `[[wikilinks]]` to cross-references within code review reports. Specifically, link the "CLAUDE.md Files Consulted" sections and any references to other review reports or plans.
- **Link rules:**
  - CLAUDE.md references stay as inline code (outside vault scope)
  - References to other reviews: `[[review_2026-03-18_16-54_gym-mcp-sdk|Gym/MCP/SDK Review]]`
  - References to context.md: `[[context]]`
  - References to task boards: `[[agent-memory-system/README|Agent Memory Board]]`
- **Why:** Connects reviews to their related plans and task boards in the graph view.
- **Risk:** Low. Adding links in report prose, not in structured sections agents parse.
- **Estimated complexity:** Medium (9 files, selective linking)

---

### Phase 4: Templates (4 tasks)

> Goal: Create Obsidian Templater templates that standardize how agents and humans create new files. Templates output frontmatter + standard headings + placeholder content.

#### Task 12: Configure Templater plugin
- **Agent:** `backend-developer`
- **Phase:** 4
- **Depends on:** Task 01
- **Priority:** High
- **Action:** Create Templater plugin configuration
- **Files to create:**
  - `development/.obsidian/plugins/templater-obsidian/manifest.json` -- plugin manifest
  - `development/.obsidian/plugins/templater-obsidian/main.js` -- plugin entry (placeholder; actual plugin installed by user)
  - `development/.obsidian/plugins/templater-obsidian/data.json` -- config pointing to `_templates/` folder
- **data.json config:**
  ```json
  {
    "templates_folder": "_templates",
    "trigger_on_file_creation": true,
    "auto_jump_to_cursor": true,
    "date_format": "YYYY-MM-DD"
  }
  ```
- **Why:** Templater is the standard Obsidian template engine. It supports dynamic date insertion, cursor placement, and folder-specific templates.
- **Risk:** Low. Plugin config only; actual plugin binary must be installed by user via Obsidian Community Plugins.
- **Estimated complexity:** Low

#### Task 13: Create code review template
- **Agent:** `backend-developer`
- **Phase:** 4
- **Depends on:** Task 12
- **Priority:** High
- **Action:** Create `development/_templates/code-review.md`
- **Template content:**
  ```markdown
  ---
  type: code-review
  date: <% tp.date.now("YYYY-MM-DD") %>
  reviewer: code-reviewer
  verdict:
  scope: <% tp.file.title.replace(/review_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_/, '') %>
  tags:
    - review
  ---

  # Code Review Report

  - **Date:** <% tp.date.now("YYYY-MM-DD HH:mm") %>
  - **Reviewer:** code-reviewer agent
  - **Verdict:**

  ## Files Reviewed

  -

  ## CLAUDE.md Files Consulted

  -

  ---

  ## Critical Issues (must fix)

  ### 1.

  - **File:**
  - **Rule violated:**
  - **Issue:**
  - **Fix:**

  ---

  ## Warnings (should fix)

  ## Suggestions (optional improvements)

  ## Passed Checks

  - [ ] Naming conventions
  - [ ] Dependency direction
  - [ ] Error handling
  - [ ] Type safety (Decimal, not float)
  - [ ] Agent scoping (agent_id)
  - [ ] Async patterns
  - [ ] Test coverage adequate
  ```
- **Why:** Ensures every new code review has consistent frontmatter for Dataview and consistent structure for agents. The template matches the existing code-review format documented in `development/code-reviews/CLAUDE.md`.
- **Risk:** Low. Template is opt-in -- agents and humans can use it or not.
- **Estimated complexity:** Low

#### Task 14: Create task file template
- **Agent:** `backend-developer`
- **Phase:** 4
- **Depends on:** Task 12
- **Priority:** High
- **Action:** Create `development/_templates/task.md`
- **Template content:**
  ```markdown
  ---
  task_id:
  title: "<% tp.file.title %>"
  type: task
  agent:
  phase: 1
  depends_on: []
  status: pending
  priority: medium
  board:
  files: []
  tags:
    - task
  ---

  # <% tp.file.title %>

  ## Assigned Agent: ``

  ## Objective

  <% tp.file.cursor() %>

  ## Context

  ## Files to Modify

  -

  ## Acceptance Criteria

  - [ ]

  ## Agent Instructions

  ## Estimated Complexity

  Low / Medium / High
  ```
- **Why:** Matches the existing task file YAML frontmatter format used by `/plan-to-tasks` skill, with added Obsidian-compatible fields (`type`, `board`, `tags`).
- **Risk:** Low. Template preserves all existing frontmatter fields agents rely on.
- **Estimated complexity:** Low

#### Task 15: Create daily note, plan, and research report templates
- **Agent:** `backend-developer`
- **Phase:** 4
- **Depends on:** Task 12
- **Priority:** Medium
- **Action:** Create three additional templates
- **Files to create:**
  - `development/_templates/daily-note.md`
  - `development/_templates/plan.md`
  - `development/_templates/research-report.md`
- **Daily note template (`daily-note.md`):**
  ```markdown
  ---
  type: daily-note
  date: <% tp.date.now("YYYY-MM-DD") %>
  tags:
    - daily
  ---

  # <% tp.date.now("YYYY-MM-DD dddd") %>

  ## Human Notes

  > Write your observations, decisions, and plans here.

  <% tp.file.cursor() %>

  ## Agent Activity

  > Auto-populated by agents. Do not edit below this line manually.

  ### Changes Made

  ### Decisions

  ### Issues Found

  ## Links

  - Previous: [[<% tp.date.now("YYYY-MM-DD", -1) %>]]
  - Next: [[<% tp.date.now("YYYY-MM-DD", 1) %>]]
  - Context: [[context]]
  ```
- **Plan template (`plan.md`):**
  ```markdown
  ---
  type: plan
  title: "<% tp.file.title %>"
  created: <% tp.date.now("YYYY-MM-DD") %>
  status: draft
  tags:
    - plan
  ---

  # <% tp.file.title %>

  ## Overview

  <% tp.file.cursor() %>

  ## Requirements

  -

  ## Architecture Changes

  ## Implementation Steps

  ### Phase 1:

  ## Testing Strategy

  ## Risks & Mitigations

  ## Success Criteria

  - [ ]
  ```
- **Research report template (`research-report.md`):**
  ```markdown
  ---
  type: research-report
  title: "<% tp.file.title %>"
  created: <% tp.date.now("YYYY-MM-DD") %>
  status: draft
  tags:
    - research
  ---

  # <% tp.file.title %>

  ## Question

  <% tp.file.cursor() %>

  ## Findings

  ## Recommendations

  ## Sources Consulted

  ## Related

  -
  ```
- **Why:** Daily notes enable the bidirectional human+agent development log. Plan and research templates standardize how new planning docs get created.
- **Risk:** Low. Template files only.
- **Estimated complexity:** Low

---

### Phase 5: MOC (Map of Content) Files (3 tasks)

> Goal: Create navigational hub notes that serve as entry points for different topic areas. These are the Obsidian equivalent of a table of contents.

#### Task 16: Create root MOC (vault home page)
- **Agent:** `backend-developer`
- **Phase:** 5
- **Depends on:** Phase 2
- **Priority:** High
- **Action:** Create `development/_moc/Home.md` as the vault landing page
- **Content:**
  ```markdown
  ---
  type: moc
  title: AiTradingAgent Development Vault
  aliases:
    - home
    - index
  tags:
    - moc
  ---

  # AiTradingAgent Development Vault

  > Knowledge base for the AiTradingAgent platform. Maintained by humans and 16 Claude Code agents.

  ## Quick Links

  - [[context|Current Development Context]]
  - [[daily-log-moc|Daily Development Log]]
  - [[task-boards-moc|All Task Boards]]
  - [[code-reviews-moc|Code Review History]]
  - [[plans-moc|Plans & Architecture]]
  - [[research-moc|Research Reports]]
  - [[wikilink-conventions|Wikilink Conventions]]

  ## Active Work

  > See [[context#Current State]] for the latest.

  ## Platform Status

  | System | Status |
  |--------|--------|
  | Backend (Python) | Production |
  | Frontend (Next.js) | Production |
  | Agent Fleet (16 agents) | Active |
  | Documentation | Complete |

  ## Vault Structure

  ```
  development/
    _moc/          MOC index files (you are here)
    _templates/    Obsidian Templater templates
    _dashboards/   Dataview dashboard queries
    daily/         Daily development log
    code-reviews/  Agent code review reports
    tasks/         Task boards (6 completed boards)
    ...            Planning docs, research reports
  ```
  ```
- **Why:** A home page gives humans a starting point. Graph view centers on this node.
- **Risk:** Low. New file creation.
- **Estimated complexity:** Low

#### Task 17: Create topic MOC files
- **Agent:** `backend-developer`
- **Phase:** 5
- **Depends on:** Task 16
- **Priority:** Medium
- **Action:** Create MOC files for each major content area
- **Files to create:**
  - `development/_moc/task-boards-moc.md`
  - `development/_moc/code-reviews-moc.md`
  - `development/_moc/plans-moc.md`
  - `development/_moc/research-moc.md`
  - `development/_moc/daily-log-moc.md`
  - `development/_moc/agents-moc.md`
- **Example (`task-boards-moc.md`):**
  ```markdown
  ---
  type: moc
  title: Task Boards
  tags:
    - moc
    - tasks
  ---

  # Task Boards

  ## Completed

  - [[tradeready-test-agent/README|TradeReady Test Agent]] (18 tasks)
  - [[agent-strategies/README|Agent Strategies]] (29 tasks)
  - [[frontend-performance-fixes/README|Frontend Performance]] (23 tasks)
  - [[agent-deployment-training/README|Agent Deployment]] (23 tasks)
  - [[agent-ecosystem/README|Agent Ecosystem]] (36 tasks)
  - [[agent-memory-system/README|Agent Memory System]] (14 tasks)

  ## In Progress

  > None currently.

  ## Dataview: All Task Boards

  ```dataview
  TABLE status, total_tasks as "Tasks", created
  FROM ""
  WHERE type = "task-board"
  SORT created DESC
  ```

  ## Dataview: Tasks by Status

  ```dataview
  TABLE WITHOUT ID
    file.link as "Task",
    agent,
    status,
    priority
  FROM ""
  WHERE type = "task"
  SORT status ASC, priority DESC
  ```
  ```
- **Example (`code-reviews-moc.md`):**
  ```markdown
  ---
  type: moc
  title: Code Reviews
  tags:
    - moc
    - review
  ---

  # Code Review History

  ## Dataview: All Reviews

  ```dataview
  TABLE date, reviewer, verdict, scope
  FROM ""
  WHERE type = "code-review"
  SORT date DESC
  ```

  ## By Verdict

  ### Needs Fixes
  ```dataview
  LIST
  FROM ""
  WHERE type = "code-review" AND verdict = "NEEDS FIXES"
  SORT date DESC
  ```

  ### Passed
  ```dataview
  LIST
  FROM ""
  WHERE type = "code-review" AND (verdict = "PASS" OR verdict = "PASS WITH WARNINGS")
  SORT date DESC
  ```
  ```
- **Why:** MOCs serve as curated entry points that Dataview queries keep automatically updated. Humans see a structured overview; the graph view shows topic clusters.
- **Risk:** Low. New files only.
- **Estimated complexity:** Medium (6 files with Dataview queries)

#### Task 18: Create agent fleet MOC
- **Agent:** `backend-developer`
- **Phase:** 5
- **Depends on:** Task 17
- **Priority:** Medium
- **Action:** Create `development/_moc/agents-moc.md` with the full agent inventory and links to their activity
- **Content:** Agent inventory table (mirroring `.claude/agents/CLAUDE.md` but with vault-internal links to reviews and tasks where each agent appears), plus Dataview query showing task count per agent across all boards
- **Dataview query for agent workload:**
  ```dataview
  TABLE WITHOUT ID
    agent as "Agent",
    length(rows) as "Total Tasks",
    length(filter(rows, (r) => r.status = "completed" OR r.status = "done")) as "Completed"
  FROM ""
  WHERE type = "task"
  GROUP BY agent
  SORT length(rows) DESC
  ```
- **Why:** Gives humans visibility into which agents do the most work and what kind of work they do. Complements the `/analyze-agents` skill with a visual, always-up-to-date view.
- **Risk:** Low. New file creation.
- **Estimated complexity:** Low

---

### Phase 6: Dataview Dashboards (3 tasks)

> Goal: Create rich Dataview-powered dashboard notes that aggregate data from across the vault.

#### Task 19: Configure Dataview plugin
- **Agent:** `backend-developer`
- **Phase:** 6
- **Depends on:** Task 01
- **Priority:** High
- **Action:** Create Dataview plugin configuration
- **Files to create:**
  - `development/.obsidian/plugins/dataview/manifest.json`
  - `development/.obsidian/plugins/dataview/main.js` (placeholder)
  - `development/.obsidian/plugins/dataview/data.json`
- **data.json config:**
  ```json
  {
    "renderNullAs": "---",
    "taskCompletionTracking": true,
    "taskCompletionUseEmojiShorthand": false,
    "taskCompletionText": "done",
    "recursiveSubTaskCompletion": false,
    "warnOnEmptyResult": true,
    "refreshEnabled": true,
    "refreshInterval": 5000,
    "defaultDateFormat": "yyyy-MM-dd",
    "maxRecursiveRenderDepth": 8,
    "tableIdColumnName": "File",
    "tableGroupColumnName": "Group"
  }
  ```
- **Why:** Dataview must be configured to recognize the frontmatter fields and date formats used in the vault.
- **Risk:** Low. Plugin config only.
- **Estimated complexity:** Low

#### Task 20: Create project health dashboard
- **Agent:** `backend-developer`
- **Phase:** 6
- **Depends on:** Tasks 04-08, 19
- **Priority:** High
- **Action:** Create `development/_dashboards/project-health.md`
- **Dataview queries to include:**
  1. **Recent code reviews** (last 5, sorted by date, showing verdict)
  2. **Task completion rate** (completed vs total across all boards)
  3. **Open tasks by priority** (high/medium/low)
  4. **Recent daily notes** (last 7 days, with links)
  5. **Plans by status** (draft/active/archived/complete)
  6. **Code review verdict distribution** (count of PASS vs NEEDS FIXES)
- **Example query (recent reviews):**
  ```dataview
  TABLE date, verdict, scope
  FROM ""
  WHERE type = "code-review"
  SORT date DESC
  LIMIT 5
  ```
- **Example query (task completion):**
  ```dataview
  TABLE WITHOUT ID
    board as "Board",
    length(rows) as "Total",
    length(filter(rows, (r) => r.status = "completed" OR r.status = "done")) as "Done",
    round(length(filter(rows, (r) => r.status = "completed" OR r.status = "done")) / length(rows) * 100) + "%" as "Progress"
  FROM ""
  WHERE type = "task"
  GROUP BY board
  ```
- **Why:** Single-page overview of project health. Replaces manually scanning context.md for status.
- **Risk:** Low. Dataview queries are read-only; they cannot modify files.
- **Estimated complexity:** Medium

#### Task 21: Create agent activity dashboard
- **Agent:** `backend-developer`
- **Phase:** 6
- **Depends on:** Tasks 18, 19
- **Priority:** Medium
- **Action:** Create `development/_dashboards/agent-activity.md`
- **Content:**
  1. Dataview query: tasks per agent (from task frontmatter)
  2. Dataview query: reviews by reviewer type
  3. Manual section: link to `development/agent-activity-log.jsonl` and instructions to run `scripts/agent-run-summary.sh` and `scripts/analyze-agent-metrics.sh`
  4. Dataview query: daily notes mentioning specific agents
- **Why:** Complements the JSONL-based activity log with a visual dashboard. Humans can see agent workload at a glance without running scripts.
- **Risk:** Low. New file creation with queries.
- **Estimated complexity:** Low

---

### Phase 7: Daily Development Log System (3 tasks)

> Goal: Create a daily note system where both humans and agents contribute. Humans write plans and observations in Obsidian; agents append activity summaries.

#### Task 22: Create daily note folder structure and seed initial notes
- **Agent:** `backend-developer`
- **Phase:** 7
- **Depends on:** Task 15
- **Priority:** High
- **Action:** Create the first daily note (`development/daily/2026-03-21.md`) as an example, and backfill skeleton notes for the last 7 days of development activity based on `development/context.md` entries
- **Files to create:**
  - `development/daily/2026-03-21.md` (today -- populated with current state from context.md)
  - `development/daily/2026-03-20.md` (backfilled from context.md March 20 entries)
  - `development/daily/2026-03-19.md`
  - `development/daily/2026-03-18.md`
- **Each note follows the daily-note template format** from Task 15, with the "Agent Activity" section populated from the corresponding context.md entries.
- **Why:** Seeding historical daily notes bootstraps the graph with connected nodes and demonstrates the intended workflow.
- **Risk:** Low. New files created from existing context.md content.
- **Estimated complexity:** Medium (4 files, content extraction from context.md)

#### Task 23: Document daily note workflow for humans
- **Agent:** `doc-updater`
- **Phase:** 7
- **Depends on:** Task 22
- **Priority:** Medium
- **Action:** Create `development/_moc/daily-log-moc.md` (if not already created in Task 17) or update it with detailed human workflow instructions
- **Content to include:**
  - How to create a daily note (Templater: `Ctrl+N`, select daily-note template, or use Obsidian daily notes plugin)
  - What to write in the "Human Notes" section (decisions, observations, blockers, plans)
  - What agents auto-populate in the "Agent Activity" section
  - How daily notes connect to `[[context]]` (context.md is the canonical record; daily notes are the working scratchpad)
  - Navigation: previous/next day links, calendar view recommendation
- **Why:** Humans need clear instructions on how to use daily notes alongside the existing context.md system.
- **Risk:** Low. Documentation only.
- **Estimated complexity:** Low

#### Task 24: Create daily note generation script
- **Agent:** `backend-developer`
- **Phase:** 7
- **Depends on:** Task 22
- **Priority:** Medium
- **Action:** Create `scripts/create-daily-note.sh` that generates today's daily note from the template (for use outside Obsidian, e.g., by agents or CI)
- **Script behavior:**
  1. Check if `development/daily/YYYY-MM-DD.md` exists for today; if yes, exit 0
  2. Copy `development/_templates/daily-note.md`, replacing Templater variables with actual values (`<% tp.date.now("YYYY-MM-DD") %>` -> today's date, etc.)
  3. Write to `development/daily/YYYY-MM-DD.md`
- **Why:** Agents and CI cannot invoke Obsidian Templater. A shell script allows the context-manager agent or a pre-commit hook to ensure a daily note always exists for today.
- **Risk:** Low. Additive script.
- **Estimated complexity:** Low

---

### Phase 8: Obsidian Git Plugin Configuration (2 tasks)

> Goal: Configure the Obsidian Git plugin so vault changes auto-commit and push. This ensures human edits in Obsidian flow back to the repo.

#### Task 25: Configure Obsidian Git plugin
- **Agent:** `backend-developer`
- **Phase:** 8
- **Depends on:** Task 01
- **Priority:** Medium
- **Action:** Create Obsidian Git plugin configuration
- **Files to create:**
  - `development/.obsidian/plugins/obsidian-git/manifest.json`
  - `development/.obsidian/plugins/obsidian-git/main.js` (placeholder)
  - `development/.obsidian/plugins/obsidian-git/data.json`
- **data.json config:**
  ```json
  {
    "autoSaveInterval": 0,
    "autoPushInterval": 0,
    "autoPullInterval": 10,
    "autoPullOnBoot": true,
    "disablePush": false,
    "pullBeforePush": true,
    "disablePopups": false,
    "listChangedFilesInMessageBody": true,
    "showStatusBar": true,
    "updateSubmodules": false,
    "syncMethod": "merge",
    "gitPath": "",
    "customMessageOnAutoBackup": "docs(vault): auto-sync {{date}}",
    "autoBackupAfterFileChange": false,
    "treeStructure": false,
    "refreshSourceControl": true
  }
  ```
- **Design decisions:**
  - `autoSaveInterval: 0` -- disabled. Humans commit manually via Obsidian Git sidebar or `/commit` skill. Auto-save creates too much noise.
  - `autoPullInterval: 10` -- pull every 10 minutes to pick up agent changes.
  - `autoPullOnBoot: true` -- always start with latest.
  - `pullBeforePush: true` -- prevent conflicts.
  - `customMessageOnAutoBackup` -- conventional commit format matching project standards.
- **Why:** Obsidian Git enables the bidirectional workflow: agents push changes via CLI git; humans pull automatically in Obsidian and push via the plugin.
- **Risk:** Medium. Git auto-pull can cause conflicts if both human and agent edit the same file simultaneously. Mitigation: the only shared mutable file is `context.md`, and the Edit tool's string-match approach minimizes conflict surface.
- **Estimated complexity:** Low

#### Task 26: Document Git workflow for humans
- **Agent:** `doc-updater`
- **Phase:** 8
- **Depends on:** Task 25
- **Priority:** Medium
- **Action:** Create `development/_moc/git-workflow.md` documenting the bidirectional sync workflow
- **Content:**
  - How Obsidian Git auto-pulls agent changes
  - How to manually commit from Obsidian (sidebar, `Ctrl+Shift+K`)
  - Conflict resolution strategy (merge, not rebase; agent files are append-only so conflicts are rare)
  - What files humans should edit vs. what agents own
  - File ownership map: `daily/*.md` (shared), `context.md` (agent-owned, human-readable), `code-reviews/*.md` (agent-owned), `tasks/**/*.md` (agent-owned), planning docs (human-owned), `_moc/*.md` (human-owned), `_dashboards/*.md` (human-owned)
- **Why:** Bidirectional sync needs clear ownership rules to prevent conflicts.
- **Risk:** Low. Documentation only.
- **Estimated complexity:** Low

---

### Phase 9: Agent Output Format Updates (3 tasks)

> Goal: Update agent output instructions to produce Obsidian-compatible frontmatter in new files. This is the minimal set of changes to agent workflows -- not rewriting agent source code.

#### Task 27: Update code-reviewer output format
- **Agent:** `context-manager`
- **Phase:** 9
- **Depends on:** Phase 4
- **Priority:** High
- **Action:** Add a note to the code-reviewer agent's system prompt instructing it to include Obsidian-compatible YAML frontmatter when creating new review files
- **File to modify:** `.claude/agents/code-reviewer.md`
- **Change:** In the "Output Format" or "Report Structure" section of the prompt, add:
  ```
  When creating a new review file in `development/code-reviews/`, include this YAML frontmatter at the top:
  ---
  type: code-review
  date: YYYY-MM-DD
  reviewer: code-reviewer
  verdict: <PASS | PASS WITH WARNINGS | NEEDS FIXES>
  scope: <brief scope descriptor>
  tags:
    - review
    - <relevant module tags>
  ---
  ```
- **Why:** Future code reviews will be Dataview-queryable from creation. The additional frontmatter does not break any existing parsing -- agents write to files with the Write tool; no code parses review files programmatically.
- **Risk:** Low. Adding instructions to agent prompt, not modifying agent code. The code-reviewer already produces structured reports; this adds a frontmatter block.
- **Estimated complexity:** Low

#### Task 28: Update context-manager daily note integration
- **Agent:** `context-manager`
- **Phase:** 9
- **Depends on:** Tasks 22, 24
- **Priority:** High
- **Action:** Add instructions to the context-manager agent's workflow for daily note maintenance
- **File to modify:** `.claude/agents/context-manager.md`
- **Change:** Add a new Step 6.5 between existing Steps 6 and 7:
  ```
  ### Step 6.5: Update Daily Note

  If `development/daily/YYYY-MM-DD.md` exists for today, append a summary of changes
  to the "Agent Activity" section. If the daily note doesn't exist, run:
  ```bash
  bash scripts/create-daily-note.sh
  ```
  Then append the summary. Format:

  ### Changes Made
  - `path/to/file.py` -- one-line description

  ### Decisions
  - Decision and reasoning

  ### Issues Found
  - Issue description
  ```
- **Why:** Connects the context-manager's existing workflow to the daily note system. The context-manager already runs after every task, so daily notes get populated automatically.
- **Risk:** Medium. Modifying a critical agent's workflow. Mitigation: the change is additive (new optional step), and the context-manager uses Edit tool (not Write), so it won't clobber human-written content in the "Human Notes" section.
- **Estimated complexity:** Low

#### Task 29: Update plan-to-tasks skill for Obsidian compatibility
- **Agent:** `backend-developer`
- **Phase:** 9
- **Depends on:** Task 14
- **Priority:** Medium
- **Action:** Update the `/plan-to-tasks` skill to include Obsidian-compatible fields in generated task file frontmatter
- **File to modify:** `.claude/skills/plan-to-tasks/SKILL.md`
- **Change:** In the task file generation template within the skill, add `type: task`, `board`, and `tags` fields to the YAML frontmatter output
- **Why:** Future task boards generated by `/plan-to-tasks` will be Dataview-queryable from creation.
- **Risk:** Low. Adding fields to YAML frontmatter; no existing fields removed or renamed.
- **Estimated complexity:** Low

---

### Phase 10: Quality Gate and Documentation (3 tasks)

> Goal: Run the standard post-change pipeline, update CLAUDE.md files, and verify everything works.

#### Task 30: Code review and testing
- **Agent:** `code-reviewer` then `test-runner`
- **Phase:** 10
- **Depends on:** All previous tasks
- **Priority:** High
- **Action:** Run the standard post-change pipeline across all modified files
- **Checks:**
  - All new files have valid YAML frontmatter (parseable by a YAML parser)
  - No existing file functionality is broken
  - No existing tests fail
  - Obsidian config JSON is valid
  - Wikilinks resolve to actual files (no broken links)
  - Frontmatter fields are consistent across file types
- **Why:** Mandatory quality gate per project standards.
- **Risk:** Low.
- **Estimated complexity:** Medium

#### Task 31: Update development/CLAUDE.md
- **Agent:** `doc-updater`
- **Phase:** 10
- **Depends on:** Task 30
- **Priority:** High
- **Action:** Update `development/CLAUDE.md` to document the Obsidian vault structure
- **Changes:**
  - Add new directories (`_templates/`, `_dashboards/`, `_moc/`, `daily/`, `.obsidian/`) to the "Subdirectories" table
  - Add note about Obsidian vault in "Purpose" section
  - Update "Patterns" section with frontmatter conventions
  - Add "Obsidian Vault" section explaining coexistence with CLAUDE.md
  - Update "Recent Changes" with dated entry
- **Why:** CLAUDE.md files are the agent navigation system. They must reflect the new directory structure.
- **Risk:** Low.
- **Estimated complexity:** Low

#### Task 32: Context manager final update
- **Agent:** `context-manager`
- **Phase:** 10
- **Depends on:** Task 31
- **Priority:** High
- **Action:** Update `development/context.md` with the Obsidian integration milestone
- **Why:** Mandatory final step per project pipeline.
- **Risk:** Low.
- **Estimated complexity:** Low

---

## Summary

| # | Task | Agent | Phase | Depends On | Priority |
|---|------|-------|-------|------------|----------|
| 01 | Create Obsidian vault configuration | `backend-developer` | 1 | -- | High |
| 02 | Create vault directory structure | `backend-developer` | 1 | 01 | High |
| 03 | Update .gitignore for Obsidian | `backend-developer` | 1 | 01 | High |
| 04 | Add frontmatter to code review files | `backend-developer` | 2 | 01 | High |
| 05 | Add frontmatter to task board READMEs | `backend-developer` | 2 | 01 | High |
| 06 | Add frontmatter to individual task files | `backend-developer` | 2 | 05 | Medium |
| 07 | Add frontmatter to planning docs | `backend-developer` | 2 | 01 | Medium |
| 08 | Add frontmatter to context.md | `backend-developer` | 2 | 01 | High |
| 09 | Define wikilink conventions | `backend-developer` | 3 | Phase 2 | High |
| 10 | Add wikilinks to task board READMEs | `backend-developer` | 3 | 05, 09 | Medium |
| 11 | Add wikilinks to code review reports | `backend-developer` | 3 | 04, 09 | Medium |
| 12 | Configure Templater plugin | `backend-developer` | 4 | 01 | High |
| 13 | Create code review template | `backend-developer` | 4 | 12 | High |
| 14 | Create task file template | `backend-developer` | 4 | 12 | High |
| 15 | Create daily note, plan, research templates | `backend-developer` | 4 | 12 | Medium |
| 16 | Create root MOC (vault home page) | `backend-developer` | 5 | Phase 2 | High |
| 17 | Create topic MOC files | `backend-developer` | 5 | 16 | Medium |
| 18 | Create agent fleet MOC | `backend-developer` | 5 | 17 | Medium |
| 19 | Configure Dataview plugin | `backend-developer` | 6 | 01 | High |
| 20 | Create project health dashboard | `backend-developer` | 6 | 04-08, 19 | High |
| 21 | Create agent activity dashboard | `backend-developer` | 6 | 18, 19 | Medium |
| 22 | Seed initial daily notes | `backend-developer` | 7 | 15 | High |
| 23 | Document daily note workflow | `doc-updater` | 7 | 22 | Medium |
| 24 | Create daily note generation script | `backend-developer` | 7 | 22 | Medium |
| 25 | Configure Obsidian Git plugin | `backend-developer` | 8 | 01 | Medium |
| 26 | Document Git workflow | `doc-updater` | 8 | 25 | Medium |
| 27 | Update code-reviewer output format | `context-manager` | 9 | Phase 4 | High |
| 28 | Update context-manager daily note step | `context-manager` | 9 | 22, 24 | High |
| 29 | Update plan-to-tasks for Obsidian | `backend-developer` | 9 | 14 | Medium |
| 30 | Code review and testing | `code-reviewer`, `test-runner` | 10 | All | High |
| 31 | Update development/CLAUDE.md | `doc-updater` | 10 | 30 | High |
| 32 | Context manager final update | `context-manager` | 10 | 31 | High |

## Agent Workload

| Agent | Task Count | Task IDs |
|-------|------------|----------|
| `backend-developer` | 23 | 01-08, 10-22, 24-25, 29 |
| `context-manager` | 3 | 27, 28, 32 |
| `doc-updater` | 3 | 23, 26, 31 |
| `code-reviewer` | 1 | 30 (review pass) |
| `test-runner` | 1 | 30 (test pass) |

## Execution Order (Parallel Groups)

### Group A -- Foundation (Tasks 01-03, no dependencies)
```
Task 01: Obsidian config     ─┐
Task 02: Directory structure  ├─ parallel after Task 01
Task 03: .gitignore update    ┘
```

### Group B -- Frontmatter (Tasks 04-08, after Group A)
```
Task 04: Code review frontmatter  ─┐
Task 05: Task board frontmatter    ├─ all parallel (depend only on Task 01)
Task 07: Planning doc frontmatter  │
Task 08: context.md frontmatter    ┘
Task 06: Individual task files     ── after Task 05
```

### Group C -- Cross-References + Plugins (Tasks 09-12, 19, after Group B)
```
Task 09: Wikilink conventions  ─┐
Task 12: Templater config      ├─ parallel (independent)
Task 19: Dataview config        ┘
Task 10: Task board wikilinks  ── after Tasks 05, 09
Task 11: Code review wikilinks ── after Tasks 04, 09
```

### Group D -- Templates + MOCs (Tasks 13-18, after Group C)
```
Task 13: Review template     ─┐
Task 14: Task template        ├─ parallel (after Task 12)
Task 15: Other templates      ┘
Task 16: Root MOC            ── after Phase 2
Task 17: Topic MOCs          ── after Task 16
Task 18: Agent MOC           ── after Task 17
```

### Group E -- Dashboards + Daily Notes (Tasks 20-24, after Group D)
```
Task 20: Project health dashboard  ─┐
Task 21: Agent activity dashboard   ├─ parallel (after Tasks 18, 19)
Task 22: Seed daily notes           ┘  (after Task 15)
Task 23: Daily note docs           ── after Task 22
Task 24: Daily note script         ── after Task 22
```

### Group F -- Git + Agent Updates (Tasks 25-29, after Group E)
```
Task 25: Obsidian Git config       ─┐
Task 27: Code-reviewer update       ├─ parallel
Task 28: Context-manager update     │  (28 after Tasks 22, 24)
Task 29: plan-to-tasks update       ┘  (29 after Task 14)
Task 26: Git workflow docs         ── after Task 25
```

### Group G -- Quality Gate (Tasks 30-32, final)
```
Task 30: Code review + test  ── after all
Task 31: CLAUDE.md update    ── after Task 30
Task 32: Context update      ── after Task 31 (FINAL)
```

---

## Testing Strategy

### Validation Checks (Task 30)

1. **YAML frontmatter validity:** Parse all `development/**/*.md` files with a YAML parser to verify frontmatter blocks are syntactically valid
   ```bash
   python -c "
   import yaml, glob
   for f in glob.glob('development/**/*.md', recursive=True):
       if '.obsidian' in f: continue
       with open(f) as fh:
           content = fh.read()
       if content.startswith('---'):
           end = content.index('---', 3)
           yaml.safe_load(content[3:end])
           print(f'OK: {f}')
   "
   ```

2. **Wikilink resolution:** Find all `[[...]]` patterns and verify target files exist
   ```bash
   grep -roh '\[\[[^]]*\]\]' development/ --include='*.md' | sort -u
   ```

3. **No CLAUDE.md contamination:** Verify no CLAUDE.md file contains `[[wikilinks]]`
   ```bash
   grep -r '\[\[' **/CLAUDE.md  # should return nothing
   ```

4. **Existing test suite:** Run `pytest tests/` to verify no agent functionality broke

5. **Agent pipeline dry run:** Run `/review-changes` on a test change to verify the code-reviewer still produces valid output

6. **Obsidian smoke test:** Open `development/` as vault in Obsidian and verify:
   - Graph view shows connected nodes
   - Dataview queries render tables
   - Templates are available via Templater
   - Daily notes create correctly
   - Search finds files by frontmatter tags

### Manual Verification (Human)

- Open vault in Obsidian
- Navigate Home MOC -> each topic MOC -> specific files
- Verify graph view shows meaningful clusters
- Create a daily note using the template
- Run a Dataview dashboard and verify data populates
- Make an edit, commit via Obsidian Git, verify it appears in `git log`

---

## Risks & Mitigations

### Risk 1: Obsidian plugin binaries not committed
- **Impact:** Obsidian won't load plugins from config alone -- users must install them
- **Severity:** Medium
- **Mitigation:** The `manifest.json` files tell Obsidian which plugins to look for. Include a `development/VAULT-SETUP.md` with one-time setup instructions: "Open vault > Settings > Community Plugins > Browse > Install: Dataview, Templater, Obsidian Git". Alternatively, the plugin `main.js` and `styles.css` files could be committed (they are open source), but this adds 500KB+ to the repo.
- **Recommendation:** Create a setup guide; do NOT commit plugin binaries. Include a verification checklist.

### Risk 2: Frontmatter breaks agent task file parsing
- **Impact:** The `/plan-to-tasks` skill reads YAML frontmatter from task files. Adding new fields could cause issues if the skill assumes a fixed set of fields.
- **Severity:** Medium
- **Mitigation:** YAML is inherently extensible -- extra fields are ignored by code that doesn't look for them. The skill reads `task_id`, `title`, `agent`, `phase`, `depends_on`, `status`, `priority`, `files`. Adding `type`, `board`, `tags` will not affect existing field reads. Verify with a test parse after Task 06.

### Risk 3: Git merge conflicts on shared files
- **Impact:** If a human edits `context.md` in Obsidian while the context-manager agent also edits it, git merge will conflict.
- **Severity:** Medium
- **Mitigation:** (1) `context.md` is agent-owned -- document this clearly in the git workflow guide. Humans read it but do not edit it. (2) Daily notes provide the human writing surface. (3) The Obsidian Git plugin's `pullBeforePush: true` reduces conflict window. (4) If a conflict occurs, the git merge will show standard conflict markers that can be resolved in any editor.

### Risk 4: Vault scope creep beyond development/
- **Impact:** If someone opens the repo root as the vault instead of `development/`, Obsidian will index source code, node_modules, etc.
- **Severity:** Low
- **Mitigation:** The `.obsidian/` folder is only inside `development/`. Obsidian only recognizes a directory as a vault if it contains `.obsidian/`. Document the correct vault path in setup instructions.

### Risk 5: Large number of files slows Obsidian
- **Impact:** 110+ task files + 30 planning docs + reviews + daily notes could slow search/graph in Obsidian
- **Severity:** Low
- **Mitigation:** This is well within Obsidian's capacity (it handles 10,000+ note vaults). The vault will have ~200 files, which is small.

### Risk 6: Context-manager daily note step fails
- **Impact:** If the daily note script errors or the file doesn't exist, the context-manager's workflow breaks at the new step
- **Severity:** Medium
- **Mitigation:** (1) The daily note step is additive and optional -- failure should log a warning, not block the rest of the workflow. (2) The script exits 0 if the note already exists. (3) Include error handling in the agent prompt: "If the daily note cannot be created or updated, log a warning and proceed with the remaining steps."

---

## Project-Specific Considerations

- **Agent scoping:** Not applicable -- this is a documentation/knowledge management feature, not a trading feature. No `agent_id` needed.
- **Decimal precision:** Not applicable -- no monetary values involved.
- **Async patterns:** Not applicable -- all changes are file creation/modification, not I/O-bound code.
- **Migration safety:** Not applicable -- no database changes.
- **Frontend sync:** Not applicable -- no API or TypeScript type changes.
- **CLAUDE.md coexistence:** CLAUDE.md files remain the agent navigation system. They do NOT get wikilinks, Obsidian frontmatter, or any Obsidian-specific features. The vault is scoped to `development/` only.
- **Agent prompt changes:** Only 3 agent files are modified (code-reviewer, context-manager, plan-to-tasks skill). Changes are additive instructions in their system prompts, not structural changes.

---

## Success Criteria

- [ ] `development/` opens as a valid Obsidian vault with graph view, search, and backlinks working
- [ ] All existing files in `development/` have valid YAML frontmatter
- [ ] Dataview dashboards show task progress, code review trends, and agent activity
- [ ] MOC files provide navigable entry points to all vault content
- [ ] Daily note template creates notes with human + agent sections
- [ ] `scripts/create-daily-note.sh` generates today's note outside Obsidian
- [ ] Code-reviewer agent produces Obsidian-compatible frontmatter in new reviews
- [ ] Context-manager appends to daily notes after each task
- [ ] Obsidian Git pulls agent changes and pushes human changes
- [ ] No existing tests fail (`pytest tests/`)
- [ ] No existing agent pipelines break (verify with `/review-changes`)
- [ ] CLAUDE.md files contain zero Obsidian-specific syntax
- [ ] Graph view shows meaningful clusters (tasks grouped by board, reviews connected to plans)
- [ ] A human can write a plan in Obsidian and an agent can read it in the next conversation

---

## Appendix: File Inventory (all new files)

```
development/
  .obsidian/
    app.json
    appearance.json
    community-plugins.json
    graph.json
    hotkeys.json
    workspace.json                    (gitignored)
    plugins/
      dataview/
        manifest.json
        main.js                       (placeholder)
        data.json
      obsidian-git/
        manifest.json
        main.js                       (placeholder)
        data.json                     (gitignored)
      templater-obsidian/
        manifest.json
        main.js                       (placeholder)
        data.json
  _templates/
    code-review.md
    task.md
    daily-note.md
    plan.md
    research-report.md
  _dashboards/
    project-health.md
    agent-activity.md
  _moc/
    Home.md
    task-boards-moc.md
    code-reviews-moc.md
    plans-moc.md
    research-moc.md
    daily-log-moc.md
    agents-moc.md
    wikilink-conventions.md
    git-workflow.md
  _attachments/
    .gitkeep
  daily/
    2026-03-18.md
    2026-03-19.md
    2026-03-20.md
    2026-03-21.md
  VAULT-SETUP.md                     (one-time Obsidian setup instructions)

scripts/
  create-daily-note.sh               (daily note generator for agents/CI)
```

**Modified files:**
- `.gitignore` (Obsidian entries)
- `.claude/agents/code-reviewer.md` (frontmatter output instruction)
- `.claude/agents/context-manager.md` (daily note step)
- `.claude/skills/plan-to-tasks/SKILL.md` (Obsidian fields in task frontmatter)
- `development/CLAUDE.md` (vault structure documentation)
- `development/context.md` (frontmatter added)
- `development/code-reviews/*.md` (9 files -- frontmatter added)
- `development/tasks/*/README.md` (6 files -- frontmatter added)
- `development/tasks/**/*.md` (~110 files -- frontmatter fields added)
- `development/*.md` (~28 files -- frontmatter added)
