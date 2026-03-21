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
  echo "Error: jq is required for analysis."
  echo "Install with: sudo apt install jq (Linux) or brew install jq (macOS)"
  echo "On Windows (Git Bash): download from https://jqlang.github.io/jq/download/"
  exit 1
fi

TOTAL=$(wc -l < "$LOG_FILE" | tr -d ' ')

echo "========================================="
echo "  Agent Activity Summary"
echo "========================================="
echo ""
echo "Log file: $LOG_FILE"
echo "Total events: $TOTAL"
echo ""

echo "--- Events by Tool ---"
jq -r '.tool' "$LOG_FILE" 2>/dev/null | sort | uniq -c | sort -rn | head -20
echo ""

echo "--- Most Touched Files ---"
jq -r 'select(.target != "n/a" and .target != null) | .target' "$LOG_FILE" 2>/dev/null | \
  sed 's|.*[/\\]||' | sort | uniq -c | sort -rn | head -20
echo ""

echo "--- Events by Day ---"
jq -r '.ts[:10]' "$LOG_FILE" 2>/dev/null | sort | uniq -c | sort -rn | head -"$DAYS"
echo ""

echo "--- Feedback Summary ---"
FEEDBACK_COUNT=$(jq -r 'select(.tool == "feedback") | .feedback' "$LOG_FILE" 2>/dev/null | wc -l | tr -d ' ')
if [ "$FEEDBACK_COUNT" -gt 0 ]; then
  jq -r 'select(.tool == "feedback") | .feedback' "$LOG_FILE" 2>/dev/null | sort | uniq -c | sort -rn
else
  echo "(No feedback recorded yet)"
fi
echo ""

echo "========================================="
echo "  End of Report"
echo "========================================="
