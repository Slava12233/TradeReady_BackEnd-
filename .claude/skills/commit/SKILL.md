---
name: commit
description: "Smart commit: stages changes, generates a conventional commit message following project format (type(scope): description), and commits. Runs ruff check before committing."
user-invocable: true
allowed-tools: Read, Grep, Glob, Bash
---

# Smart Commit

Create a well-formatted git commit for the current changes following the project's commit format.

## Process

### 1. Check what changed
```bash
git status
git diff --stat
git diff --cached --stat
```

### 2. Pre-commit checks
Run lint on changed Python files only:
```bash
ruff check --fix $(git diff --name-only --diff-filter=ACMR | grep '\.py$' | tr '\n' ' ')
```
If any errors remain after auto-fix, report them and stop.

### 3. Stage changes
- If nothing is staged, stage all modified/new files (but NOT `.env`, `*.key`, `*.pem`, `*.crt`, credentials)
- If files are already staged, use those

### 4. Generate commit message
Follow the project format exactly:
```
type(scope): description
```

**Types:** `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`
**Scope:** The primary module affected (e.g., `agents`, `order-engine`, `api`, `frontend`, `backtesting`)

Rules:
- Keep the first line under 72 characters
- Use imperative mood ("add feature" not "added feature")
- Focus on WHY not WHAT
- If multiple modules changed, pick the most significant as scope

### 5. Commit
```bash
git commit -m "$(cat <<'EOF'
type(scope): description

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### 6. Show result
Print the commit hash and message for confirmation.

## Rules
- Never commit `.env`, secrets, credentials, or API keys
- Never amend existing commits unless explicitly asked
- Always run ruff check before committing
- Use `$ARGUMENTS` as the commit message if provided, but still format it properly
