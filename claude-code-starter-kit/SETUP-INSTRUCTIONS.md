# Setup Instructions — Claude Code Starter Kit

## Prerequisites

- Claude Code CLI installed
- A git repository (initialized)

## Step-by-Step Setup

### Step 1: Copy Files Into Your Project

```bash
# Copy settings
mkdir -p .claude/agents .claude/skills .claude/rules
cp templates/settings.json .claude/settings.json
cp templates/settings.local.json.example .claude/settings.local.json

# Copy agents (16 agents)
cp templates/agents/*.md .claude/agents/

# Copy skills (6 skills)
cp -r templates/skills/* .claude/skills/

# Copy rules
cp templates/rules/*.md .claude/rules/

# Copy root CLAUDE.md
cp templates/ROOT-CLAUDE.md.template ./CLAUDE.md

# Copy development templates
mkdir -p development
cp templates/development/CLAUDE.md.template development/CLAUDE.md
cp templates/development/context.md.template development/context.md

# Update .gitignore
echo ".claude/settings.local.json" >> .gitignore
echo ".claude/agent-memory-local/" >> .gitignore
```

### Step 2: Run the Bootstrap Skill

Open Claude Code in your project root and type:

```
/bootstrap-project
```

This will:
1. Scan your entire codebase structure
2. Detect your tech stack, languages, frameworks
3. Generate a CLAUDE.md file in every major directory
4. Customize the root CLAUDE.md with your project-specific details
5. Update agent templates with your project's conventions
6. Replace all `{{PLACEHOLDER}}` markers with detected values

### Step 3: Customize Settings

**`.claude/settings.json`** (shared, committed):
1. Replace `{{PLACEHOLDER}}` values with your actual commands (test, lint, build)
2. Add project-specific permission patterns if needed
3. Configure environment variables

**`.claude/settings.local.json`** (personal, gitignored):
1. Add any personal permission overrides
2. Override model preferences if desired

### Step 4: Customize Agents

After bootstrap completes, review and customize each agent in `.claude/agents/`:

1. **code-reviewer.md** — Add your project's specific coding standards
2. **test-runner.md** — Update the test mapping table for your test files
3. **planner.md** — Update the CLAUDE.md quick reference table
4. **context-manager.md** — Adjust the sections tracked for your workflow
5. **backend-developer.md** — Add framework-specific patterns
6. **frontend-developer.md** — Add component/styling conventions

### Step 5: Customize Rules

Edit `.claude/rules/` files to match your project:

1. **code-style.md** — Your language/framework naming, import, and formatting rules
2. **testing.md** — Your test framework, patterns, and conventions
3. **security.md** — Your security requirements and patterns

### Step 6: Verify

Run `/sync-context` to verify all CLAUDE.md files are accurate and up-to-date.

Then run `/run-checks` to verify lint, types, and tests pass.

## Using Skills

After setup, you have these slash commands available:

| Command | When to Use |
|---------|-------------|
| `/commit` | When you're ready to commit changes |
| `/review-changes` | After making changes, before committing |
| `/run-checks` | Quick feedback during development |
| `/sync-context` | Periodically to catch CLAUDE.md drift |
| `/plan-to-tasks <file>` | When you have a plan to break into tasks |
| `/bootstrap-project` | One-time initial setup |

## Understanding Pipelines

Agents aren't independent — they form ordered pipelines:

**Every code change triggers:**
```
code-reviewer → test-runner → context-manager
```

**Additional agents prepend based on change type:**
- API changes: `api-sync-checker` → `doc-updater` → standard pipeline
- Security changes: `security-reviewer` → `security-auditor` → standard pipeline
- Performance changes: `perf-checker` → standard pipeline
- Database changes: `migration-helper` → `deploy-checker` → `context-manager`

## Advanced: Agent Memory

Some agents have `memory: project` enabled. This means they learn across conversations:

- **code-reviewer** remembers recurring issues
- **context-manager** remembers project patterns
- **planner** remembers past architectural decisions
- **security-reviewer** remembers past vulnerabilities

Memory files are stored in `.claude/agent-memory/` (committed) and `.claude/agent-memory-local/` (gitignored).

## Ongoing Maintenance

- The `context-manager` agent keeps `development/context.md` fresh
- The `doc-updater` agent keeps CLAUDE.md files updated when code changes
- Run `/sync-context` periodically to catch any drift
- Update agents when project conventions evolve

## Removing Agents You Don't Need

Not every project needs all 16 agents. Delete any `.claude/agents/*.md` file you don't need:

| If your project has no... | Remove these agents |
|---------------------------|-------------------|
| Database | `migration-helper.md` |
| Frontend | `frontend-developer.md`, `api-sync-checker.md` |
| Production deployment | `deploy-checker.md` |
| E2E testing | `e2e-tester.md` |
| ML/RL training | `ml-engineer.md` |
| Backend code | `backend-developer.md` |

The minimum viable set is: `code-reviewer`, `test-runner`, `context-manager`, `planner`.
