---
name: review-changes
description: "Run the full post-change pipeline on current uncommitted changes: code-reviewer, test-runner, then context-manager. Use after making changes to verify quality before committing."
user-invocable: true
allowed-tools: Read, Write, Edit, Grep, Glob, Bash, Agent
---

# Review Changes Pipeline

Run the mandatory post-change agent pipeline on current uncommitted changes.

## Process

### 1. Identify changes
```bash
git diff --name-only
git diff --cached --name-only
```
Report which files changed and in which modules.

### 2. Determine pipeline type
Based on the changed files, decide which pipeline to run:

- **Files in `src/api/schemas/`, `src/api/routes/`, `Frontend/src/lib/`**: API/Schema pipeline (add api-sync-checker + doc-updater)
- **Files in `src/accounts/`, `src/api/middleware/`, `src/risk/`**: Security pipeline (add security-reviewer + security-auditor)
- **Files with DB queries, async code, caching**: Performance pipeline (add perf-checker)
- **Files in `alembic/`**: Migration pipeline (add migration-helper)
- **All other changes**: Standard pipeline

### 3. Run pipeline agents in order

**Standard pipeline (always runs):**
1. Delegate to `code-reviewer` — review changed files against CLAUDE.md standards
2. Delegate to `test-runner` — run relevant tests, write missing ones
3. Delegate to `context-manager` — update development/context.md and CLAUDE.md files

**Extended pipeline steps (if needed):**
- `api-sync-checker` before code-reviewer (for API changes)
- `security-reviewer` before code-reviewer (for auth/security changes)
- `perf-checker` before code-reviewer (for DB/async changes)
- `doc-updater` after code-reviewer (for API changes)

### 4. Summary
Report the results of each agent:
```
Pipeline Results:
- code-reviewer: X issues found (Y critical, Z warnings)
- test-runner: X tests ran, Y passed, Z failed
- context-manager: updated N files
```

### 5. Capture feedback (optional)

After reporting pipeline results, ask the user:

> **Were the code-reviewer findings useful?** [all-useful / some-useful / not-useful / skip]

If the user responds (not "skip"):
1. Log the feedback to the activity log:
```bash
echo '{"ts":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'","tool":"feedback","target":"code-reviewer","feedback":"RESPONSE"}' >> development/agent-activity-log.jsonl
```
2. If "not-useful", ask briefly what was wrong (optional — don't block workflow)
3. Update `.claude/agent-memory/code-reviewer/MEMORY.md` with any patterns to avoid

If the user skips or doesn't respond, proceed without logging.

## Rules
- Run agents sequentially, not in parallel (each depends on the previous)
- If code-reviewer finds CRITICAL issues, stop and report before running test-runner
- If tests fail, report the failures clearly with file:line references
- Always run context-manager as the final step
- Feedback capture is optional — never block the workflow waiting for feedback
- If feedback indicates false positives, update agent memory to prevent recurrence
