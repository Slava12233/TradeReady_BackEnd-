#!/bin/bash
# Log agent tool usage to JSONL activity log
# Called by PostToolUse hook in .claude/settings.json
# Receives hook event JSON on stdin
#
# Output: development/agent-activity-log.jsonl (append-only)

LOG_FILE="development/agent-activity-log.jsonl"

# Read hook input with timeout protection (Windows bash can hang on stdin)
HOOK_INPUT=$(timeout 3 cat 2>/dev/null || echo '{}')

# Extract fields
if command -v jq &>/dev/null; then
  TOOL=$(echo "$HOOK_INPUT" | jq -r '.tool_name // "unknown"' 2>/dev/null || echo "unknown")
  FILE=$(echo "$HOOK_INPUT" | jq -r '.tool_input.file_path // .tool_input.command // "n/a"' 2>/dev/null | head -c 200 || echo "n/a")
else
  # Pure bash fallback: extract tool_name and file_path from JSON
  TOOL=$(echo "$HOOK_INPUT" | sed -n 's/.*"tool_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
  TOOL=${TOOL:-unknown}
  FILE=$(echo "$HOOK_INPUT" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
  if [ -z "$FILE" ]; then
    FILE=$(echo "$HOOK_INPUT" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -c 200)
  fi
  FILE=${FILE:-n/a}
fi

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%Y-%m-%dT%H:%M:%SZ)

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null

# Append event
echo "{\"ts\":\"$TIMESTAMP\",\"tool\":\"$TOOL\",\"target\":\"$FILE\"}" >> "$LOG_FILE" 2>/dev/null

# Always exit 0 — never block the agent
exit 0
