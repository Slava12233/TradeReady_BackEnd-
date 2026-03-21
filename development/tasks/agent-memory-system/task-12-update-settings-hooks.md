---
task_id: 12
title: "Update settings.json with logging hooks"
type: task
agent: "context-manager"
phase: 2
depends_on: [9, 10]
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "high"
files:
  - ".claude/settings.json"
tags:
  - task
  - agent
  - memory
---

# Task 12: Update settings.json with logging hooks

## Assigned Agent: `context-manager`

## Objective
Update `.claude/settings.json` to add PostToolUse hooks that trigger the activity logging scripts created in Tasks 09-10.

## Context
Phase 2 of Agent Memory Strategy. The logging scripts exist — now wire them into Claude Code's hook system so they fire automatically on every tool use.

## Files to Modify
- `.claude/settings.json` — update the `hooks.PostToolUse` array

## Current State
```json
"hooks": {
  "PostToolUse": [
    {
      "matcher": "Write|Edit",
      "hooks": [
        {
          "type": "command",
          "command": "echo 'File modified — remember to run code-reviewer + test-runner pipeline'",
          "timeout": 5
        }
      ]
    }
  ]
}
```

## Target State
Keep the existing reminder hook AND add the logging hook:
```json
"hooks": {
  "PostToolUse": [
    {
      "matcher": "Write|Edit",
      "hooks": [
        {
          "type": "command",
          "command": "echo 'File modified — remember to run code-reviewer + test-runner pipeline'",
          "timeout": 5
        }
      ]
    },
    {
      "matcher": "Write|Edit|Bash",
      "hooks": [
        {
          "type": "command",
          "command": "bash scripts/log-agent-activity.sh",
          "timeout": 5
        }
      ]
    }
  ]
}
```

## Acceptance Criteria
- [ ] Existing reminder hook is preserved (not removed or modified)
- [ ] New logging hook added for Write, Edit, and Bash tools
- [ ] Hook command points to correct script path
- [ ] Timeout set to 5 seconds
- [ ] JSON is valid (no syntax errors)
- [ ] Settings file maintains all other existing configuration

## Agent Instructions
Read the current `.claude/settings.json` first. Add the new hook entry to the `PostToolUse` array without modifying any other settings (permissions, env, deny rules). Validate JSON syntax.

## Estimated Complexity
Low — add one JSON object to existing array.
