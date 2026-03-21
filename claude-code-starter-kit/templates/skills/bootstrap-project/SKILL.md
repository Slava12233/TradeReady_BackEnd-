---
name: bootstrap-project
description: "One-shot project bootstrap: scans the entire codebase, detects the tech stack, generates CLAUDE.md files in every major directory, customizes agents and rules for the project's conventions, and updates the root CLAUDE.md with a complete module index. Use this once when setting up Claude Code on a new or existing project."
disable-model-invocation: true
---

# Bootstrap Claude Code for This Project

Scan the entire codebase and generate a complete CLAUDE.md navigation layer + customize all agents and rules for this specific project.

## Phase 1: Detect Tech Stack

### Step 1: Scan project root
Look for these indicators:

**Package/dependency files:**
- `package.json` → Node.js/TypeScript (check for framework: Next.js, React, Vue, Angular, Express, etc.)
- `pyproject.toml` / `requirements.txt` / `Pipfile` → Python (check for framework: FastAPI, Django, Flask, etc.)
- `Cargo.toml` → Rust
- `go.mod` → Go
- `Gemfile` → Ruby/Rails
- `pom.xml` / `build.gradle` → Java/Kotlin
- `composer.json` → PHP/Laravel

**Config files:**
- `tsconfig.json` → TypeScript
- `tailwind.config.*` → Tailwind CSS
- `.eslintrc*` → ESLint
- `ruff.toml` / `pyproject.toml [tool.ruff]` → Ruff
- `docker-compose.yml` → Docker
- `Dockerfile` → Docker
- `.github/workflows/` → GitHub Actions CI/CD
- `alembic.ini` → Alembic (Python DB migrations)
- `prisma/` → Prisma (TypeScript DB migrations)

**Database indicators:**
- `alembic/` → PostgreSQL/SQLAlchemy
- `prisma/` → Prisma/PostgreSQL
- `migrations/` → Django/Rails migrations
- `*.db` / `sqlite*` → SQLite

### Step 2: Record findings
Create a mental model of:
- **Primary language(s):** e.g., Python 3.12, TypeScript 5.x
- **Backend framework:** e.g., FastAPI, Express, Django
- **Frontend framework:** e.g., Next.js, React, Vue
- **Database:** e.g., PostgreSQL, MongoDB, SQLite
- **Migration tool:** e.g., Alembic, Prisma, Django ORM
- **Package manager:** e.g., pip/uv, pnpm, cargo
- **Test framework:** e.g., pytest, vitest, jest, go test
- **Linter:** e.g., ruff, eslint, clippy
- **Type checker:** e.g., mypy, tsc, go vet
- **CI/CD:** e.g., GitHub Actions, GitLab CI
- **Containerization:** Docker Compose, Kubernetes

## Phase 2: Map the Codebase

### Step 3: Discover all directories
```bash
find . -type d -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/__pycache__/*' -not -path '*/venv/*' -not -path '*/.venv/*' -not -path '*/.next/*' -not -path '*/dist/*' -not -path '*/build/*' -not -path '*/.claude/*' | sort
```

### Step 4: Identify major modules
A "major module" deserves its own CLAUDE.md if it:
- Contains 3+ source files
- Has a distinct responsibility (not just a utility)
- Would benefit from documented patterns/gotchas
- Is a top-level directory or a significant subdirectory

Typical structure to look for:
```
src/                    ← CLAUDE.md (backend overview)
  auth/                 ← CLAUDE.md (auth module)
  api/                  ← CLAUDE.md (API layer)
    routes/             ← CLAUDE.md (route inventory)
    middleware/          ← CLAUDE.md (middleware stack)
  database/             ← CLAUDE.md (models, repos)
  services/             ← CLAUDE.md (business logic)
tests/                  ← CLAUDE.md (test patterns)
  unit/                 ← CLAUDE.md (unit test inventory)
  integration/          ← CLAUDE.md (integration setup)
frontend/               ← CLAUDE.md (frontend architecture)
  src/components/       ← CLAUDE.md (component organization)
  src/hooks/            ← CLAUDE.md (hook patterns)
  src/stores/           ← CLAUDE.md (state management)
docs/                   ← CLAUDE.md (doc inventory)
scripts/                ← CLAUDE.md (script inventory)
```

## Phase 3: Generate CLAUDE.md Files

### Step 5: For each major module, generate a CLAUDE.md

For each identified module:

1. **Glob the directory** to list all files
2. **Read 2-3 key files** to understand patterns (the main file, index file, or largest file)
3. **Grep for exports/public API** — classes, functions, endpoints
4. **Generate the CLAUDE.md** using this template:

```markdown
# {Module Name}

<!-- last-updated: YYYY-MM-DD -->

> One-line purpose of this module.

## What This Module Does

2-3 sentence overview.

## Key Files

| File | Purpose |
|------|---------|
| `file.ext` | What it does |

## Architecture & Patterns

- Key patterns used
- Important abstractions
- Dependency direction

## Public API / Interfaces

Key classes, functions, or endpoints.

## Dependencies

- **Depends on:** [modules this imports from]
- **Used by:** [modules that import this]

## Common Tasks

### Adding a new X
1. Step 1
2. Step 2

## Gotchas & Pitfalls

- Non-obvious things

## Recent Changes

- `YYYY-MM-DD` — Initial CLAUDE.md created by bootstrap
```

### Step 6: Generate root CLAUDE.md

Update the root `CLAUDE.md` file:

1. **Fill in the CLAUDE.md Index** — list every generated CLAUDE.md with its path and one-line description
2. **Fill in Architecture Overview** — based on what you discovered
3. **Fill in Commands** — build, test, lint, type-check, dev server commands from package files
4. **Fill in Code Standards** — from linter config, existing code patterns
5. **Fill in Environment Variables** — from `.env.example`, `.env`, or config files
6. **Replace all `{{PLACEHOLDER}}` markers** with detected values

## Phase 4: Customize Agents

### Step 7: Update agent templates

For each agent in `.claude/agents/`:

1. Read the current template
2. Update project-specific references:
   - Test commands and frameworks
   - Lint/type-check commands
   - File naming conventions
   - Framework-specific patterns
   - Database/migration tool references
3. Write the updated agent file

Key customizations per agent:
- **code-reviewer**: Add project-specific coding standards
- **test-runner**: Update test file mapping table, test commands
- **deploy-checker**: Update build/test/lint commands
- **migration-helper**: Update for specific migration tool (Alembic, Prisma, etc.)
- **frontend-developer**: Update for specific frontend framework

## Phase 5: Customize Rules

### Step 8: Generate rule files

Update `.claude/rules/`:

**code-style.md:**
```markdown
---
paths:
  - "**/*"
---
# Code Style Rules

[Generated from linter config and observed patterns]
```

**testing.md:**
```markdown
---
paths:
  - "tests/**/*"
  - "**/*.test.*"
  - "**/*.spec.*"
---
# Testing Rules

[Generated from test framework config and existing test patterns]
```

**security.md:**
```markdown
---
paths:
  - "**/*"
---
# Security Rules

[Generated from observed auth patterns, env var usage, etc.]
```

## Phase 6: Initialize Development Context

### Step 9: Create development context

Create `development/context.md`:
```markdown
# Development Context Log

<!-- Maintained by context-manager agent -->

## Current State

**Active work:** Project bootstrapped with Claude Code agentic layer
**Last session:** YYYY-MM-DD — Initial setup
**Next steps:** Begin development
**Blocked:** None

## Recent Activity

### YYYY-MM-DD — Claude Code Bootstrap

**Changes:**
- Generated CLAUDE.md files across the entire codebase
- Configured 14 custom agents in `.claude/agents/`
- Set up skills: sync-context, bootstrap-project
- Created development context tracking

**Decisions:**
- CLAUDE.md hierarchy follows directory structure
- Agents customized for [detected tech stack]
```

## Phase 7: Report

### Step 10: Print summary

```
Bootstrap Complete!

Tech Stack Detected:
- Language: [X]
- Framework: [X]
- Database: [X]
- Test Framework: [X]

Files Generated:
- CLAUDE.md files: X (in Y directories)
- Agents customized: 14
- Rules created: 3
- Skills configured: 2

Next Steps:
1. Review the generated CLAUDE.md files for accuracy
2. Run /sync-context to verify everything is correct
3. Start developing — agents will maintain docs automatically
```

## Rules

- **Read before writing** — always read existing files in a module before generating its CLAUDE.md
- **Be accurate** — only document what you actually observe in the code
- **Don't guess** — if you can't determine something, leave a {{PLACEHOLDER}} for manual filling
- **Preserve existing CLAUDE.md** — if a module already has one, update it rather than overwriting
- **Keep it concise** — CLAUDE.md files should be navigation aids, not novels
