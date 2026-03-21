---
task_id: 09
title: "Create log-agent-activity.sh hook script"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "high"
files:
  - "scripts/log-agent-activity.sh"
tags:
  - task
  - agent
  - memory
---

# Task 09: Create log-agent-activity.sh hook script

## Assigned Agent: `backend-developer`

## Objective
Create a shell script that captures agent tool usage events and appends them as structured JSON to an activity log file. This script will be triggered by Claude Code's PostToolUse hook.

## Context
Phase 2 of Agent Memory Strategy. This script is the core logging mechanism — it captures what agents do (tools used, files modified) in a queryable JSONL format.

## Files to Create
- `scripts/log-agent-activity.sh`

## Implementation Details

The script receives hook event data via stdin as JSON. It should:

1. Read JSON from stdin
2. Extract key fields: tool name, tool input (file path, command, etc.)
3. Add timestamp
4. Append a single JSON line to `development/agent-activity-log.jsonl`
5. Exit with code 0 (never block the tool)

```bash
#!/bin/bash
# Log agent tool usage to JSONL activity log
# Called by PostToolUse hook in .claude/settings.json
# Receives hook event JSON on stdin

set -euo pipefail

LOG_FILE="development/agent-activity-log.jsonl"

# Read hook input
HOOK_INPUT=$(cat 2>/dev/null || echo '{}')

# Extract fields (gracefully handle missing jq)
if command -v jq &>/dev/null; then
  TOOL=$(echo "$HOOK_INPUT" | jq -r '.tool_name // "unknown"')
  FILE=$(echo "$HOOK_INPUT" | jq -r '.tool_input.file_path // .tool_input.command // "n/a"' | head -c 200)
else
  TOOL="unknown"
  FILE="n/a"
fi

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%Y-%m-%dT%H:%M:%SZ)

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Append event (atomic write)
echo "{\"ts\":\"$TIMESTAMP\",\"tool\":\"$TOOL\",\"target\":\"$FILE\"}" >> "$LOG_FILE"

exit 0
```

## Acceptance Criteria
- [ ] Script is executable (`chmod +x`)
- [ ] Handles missing `jq` gracefully (degrades to "unknown")
- [ ] Never exits with non-zero code (would block agent)
- [ ] Appends valid JSON lines to `development/agent-activity-log.jsonl`
- [ ] Creates log file and directory if they don't exist
- [ ] Runs in <1 second (hook timeout is 5s)
- [ ] Works on both Linux/macOS and Git Bash (Windows)

## Agent Instructions
Read existing scripts in `scripts/` for style conventions (see `scripts/CLAUDE.md`). The script must be robust — a hook failure would block agent work. Always exit 0. Test with `echo '{"tool_name":"Write","tool_input":{"file_path":"test.py"}}' | bash scripts/log-agent-activity.sh`.

## Estimated Complexity
Low — straightforward shell script with JSON parsing.
