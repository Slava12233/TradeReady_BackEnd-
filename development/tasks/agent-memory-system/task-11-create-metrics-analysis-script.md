---
task_id: 11
title: "Create analyze-agent-metrics.sh analysis script"
type: task
agent: "backend-developer"
phase: 2
depends_on: [9]
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "medium"
files:
  - "scripts/analyze-agent-metrics.sh"
tags:
  - task
  - agent
  - memory
---

# Task 11: Create analyze-agent-metrics.sh analysis script

## Assigned Agent: `backend-developer`

## Objective
Create a script that analyzes the JSONL activity log and generates a human-readable summary of agent activity metrics.

## Context
Phase 2 of Agent Memory Strategy. This script reads the log created by Task 09 and provides insights: which tools are used most, which files are touched most, activity volume over time.

## Files to Create
- `scripts/analyze-agent-metrics.sh`

## Implementation Details

```bash
#!/bin/bash
# Analyze agent activity log and produce summary metrics
# Requires: jq
# Usage: bash scripts/analyze-agent-metrics.sh [days=7]

set -euo pipefail

LOG_FILE="development/agent-activity-log.jsonl"
DAYS=${1:-7}

if [ ! -f "$LOG_FILE" ]; then
  echo "No activity log found at $LOG_FILE"
  echo "Run some agent tasks first to generate activity data."
  exit 0
fi

if ! command -v jq &>/dev/null; then
  echo "Error: jq is required. Install with: sudo apt install jq (or brew install jq)"
  exit 1
fi

TOTAL=$(wc -l < "$LOG_FILE")
echo "=== Agent Activity Summary ==="
echo "Log file: $LOG_FILE"
echo "Total events: $TOTAL"
echo ""

echo "--- Events by Tool ---"
jq -r '.tool' "$LOG_FILE" | sort | uniq -c | sort -rn | head -20
echo ""

echo "--- Most Touched Files ---"
jq -r 'select(.target != "n/a") | .target' "$LOG_FILE" | sort | uniq -c | sort -rn | head -20
echo ""

echo "--- Events by Day ---"
jq -r '.ts[:10]' "$LOG_FILE" | sort | uniq -c | sort -rn | head -"$DAYS"
echo ""

echo "=== End of Report ==="
```

## Acceptance Criteria
- [ ] Script requires `jq` and exits gracefully if not installed
- [ ] Handles empty or missing log file
- [ ] Shows: events by tool, most-touched files, events by day
- [ ] Accepts optional `days` argument (default 7)
- [ ] Output is readable in terminal

## Estimated Complexity
Low — jq queries over JSONL file.
