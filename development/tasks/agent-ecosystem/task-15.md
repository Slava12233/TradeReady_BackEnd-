---
task_id: 15
title: "CLI chat interface (REPL)"
agent: "backend-developer"
phase: 1
depends_on: [13, 7]
status: "pending"
priority: "high"
files: ["agent/cli.py"]
---

# Task 15: CLI chat interface (REPL)

## Assigned Agent: `backend-developer`

## Objective
Create an interactive CLI REPL for chatting with the agent. Supports natural language input, slash commands, colored output, and session persistence.

## Files to Create/Modify
- `agent/cli.py` — interactive REPL (new file)
- `agent/__main__.py` — add `chat` subcommand (modify)

## Key Design
```
$ python -m agent chat
🤖 TradeReady Agent v2 — Type /help for commands, /quit to exit
Session: abc123 (resumed)

You: What's the market looking like?
Agent: Based on current data...

You: /portfolio
Agent: [formatted portfolio table]

You: /trade BTC long
Agent: I'd suggest buying BTC at $67,234...
  Confidence: 0.78
  Risk: Medium
  [Approve? y/n]
```

## Slash Commands
- `/help` — show available commands
- `/trade [symbol] [direction]` — initiate trade discussion
- `/analyze [symbol]` — analyze a specific market
- `/portfolio` — show portfolio summary
- `/journal [entry]` — write or read journal
- `/learn` — show recent learnings
- `/permissions` — show current permissions
- `/status` — agent health and stats
- `/session [new|list|resume ID]` — session management
- `/quit` or `/exit` — exit REPL

## Acceptance Criteria
- [ ] REPL starts with session resume or new session creation
- [ ] All slash commands work correctly
- [ ] Natural language routes through intent router
- [ ] Colored/formatted output using `rich` library
- [ ] Markdown rendering in terminal
- [ ] Session persists across CLI restarts
- [ ] Ctrl+C handled gracefully (not crash)
- [ ] `/trade` shows trade proposals with approve/reject flow
- [ ] Added as `chat` subcommand to `agent/__main__.py`

## Dependencies
- Task 13 (agent server), Task 07 (intent router)

## Agent Instructions
1. Read `agent/__main__.py` for existing CLI structure
2. Use `rich` for terminal formatting (already in agent deps or add it)
3. Use `prompt_toolkit` or plain `input()` for REPL input
4. Route slash commands directly, natural language through IntentRouter
5. Session auto-resume: check for active session on startup
6. Entry point: `python -m agent chat [--agent-id ID] [--session-id ID]`

## Estimated Complexity
Medium — REPL with command routing, formatting, and session management.
