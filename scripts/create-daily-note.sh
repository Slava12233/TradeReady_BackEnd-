#!/usr/bin/env bash
# Creates today's daily note in development/daily/ if it doesn't exist.
# Used by agents and CI when Obsidian Templater is not available.

set -euo pipefail

VAULT_DIR="$(cd "$(dirname "$0")/../development" && pwd)"
TODAY=$(date +%Y-%m-%d)
DAY_NAME=$(date +%A)
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d 2>/dev/null || echo "YYYY-MM-DD")
TOMORROW=$(date -d "tomorrow" +%Y-%m-%d 2>/dev/null || date -v+1d +%Y-%m-%d 2>/dev/null || echo "YYYY-MM-DD")
NOTE_PATH="${VAULT_DIR}/daily/${TODAY}.md"

if [[ -f "$NOTE_PATH" ]]; then
  echo "Daily note already exists: ${NOTE_PATH}"
  exit 0
fi

mkdir -p "${VAULT_DIR}/daily"

cat > "$NOTE_PATH" << EOF
---
type: daily-note
date: ${TODAY}
tags:
  - daily
---

# ${TODAY} ${DAY_NAME}

## Human Notes

> Write your observations, decisions, and plans here.

## Agent Activity

> Auto-populated by agents. Do not edit below this line manually.

### Changes Made

### Decisions

### Issues Found

## Links

- Previous: [[${YESTERDAY}]]
- Next: [[${TOMORROW}]]
- Context: [[context]]
EOF

echo "Created daily note: ${NOTE_PATH}"
