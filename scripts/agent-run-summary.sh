#!/bin/bash
# Generate a summary of changes made during an agent run
# Can be called by Stop hook or manually after agent completes
#
# Output: development/agent-runs/<date>/run-<time>.md

DATE=$(date +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d)
TIME=$(date +%H-%M-%S 2>/dev/null || date +%H-%M-%S)
RUN_DIR="development/agent-runs/$DATE"
SUMMARY_FILE="$RUN_DIR/run-$TIME.md"

mkdir -p "$RUN_DIR" 2>/dev/null

BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
DIFF_STAT=$(git diff HEAD --stat 2>/dev/null || echo "No changes detected")
STAGED_STAT=$(git diff --cached --stat 2>/dev/null || echo "No staged changes")

cat > "$SUMMARY_FILE" <<EOF
# Agent Run Summary — $DATE $TIME

**Branch:** $BRANCH
**Timestamp:** $(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%Y-%m-%dT%H:%M:%SZ)

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
