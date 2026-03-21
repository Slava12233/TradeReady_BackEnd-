---
task_id: 10
title: "Create agent-run-summary.sh hook script"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "medium"
files:
  - "scripts/agent-run-summary.sh"
tags:
  - task
  - agent
  - memory
---

# Task 10: Create agent-run-summary.sh hook script

## Assigned Agent: `backend-developer`

## Objective
Create a shell script that generates a markdown summary of changes made during an agent run. Designed to be triggered by a Stop hook or called manually after an agent completes.

## Context
Phase 2 of Agent Memory Strategy. Complements the per-event logging (Task 09) with a per-run summary that captures the overall outcome.

## Files to Create
- `scripts/agent-run-summary.sh`

## Implementation Details

The script should:
1. Capture git diff stats (files changed, insertions, deletions)
2. Generate a timestamped summary file in `development/agent-runs/`
3. Include the date, git branch, and diff summary

```bash
#!/bin/bash
# Generate a summary of changes made during an agent run
# Can be called by Stop hook or manually after agent completes

set -euo pipefail

DATE=$(date +%Y-%m-%d)
TIME=$(date +%H-%M-%S)
RUN_DIR="development/agent-runs/$DATE"
SUMMARY_FILE="$RUN_DIR/run-$TIME.md"

mkdir -p "$RUN_DIR"

BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
DIFF_STAT=$(git diff HEAD --stat 2>/dev/null || echo "No changes detected")
STAGED_STAT=$(git diff --cached --stat 2>/dev/null || echo "No staged changes")

cat > "$SUMMARY_FILE" <<EOF
# Agent Run Summary — $DATE $TIME

**Branch:** $BRANCH
**Timestamp:** $(date -u +%Y-%m-%dT%H:%M:%SZ)

## Changes (unstaged)
\`\`\`
$DIFF_STAT
\`\`\`

## Changes (staged)
\`\`\`
$STAGED_STAT
\`\`\`
EOF

echo "Run summary saved to $SUMMARY_FILE"
exit 0
```

## Acceptance Criteria
- [ ] Script is executable (`chmod +x`)
- [ ] Creates dated directory structure in `development/agent-runs/`
- [ ] Summary includes branch, timestamp, and diff stats
- [ ] Multiple runs on same day create separate files (timestamped)
- [ ] Works when no changes exist (graceful handling)
- [ ] Always exits 0

## Estimated Complexity
Low — straightforward git commands + file writing.
