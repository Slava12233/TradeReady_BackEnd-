---
task_id: 07
title: "Intent router for conversation system"
type: task
agent: "backend-developer"
phase: 1
depends_on: [5]
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "medium"
files: ["agent/conversation/router.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 07: Intent router for conversation system

## Assigned Agent: `backend-developer`

## Objective
Create an intent classification router that determines what the user wants and routes to the appropriate handler (trade execution, portfolio review, journal, analysis, etc.).

## Files to Create
- `agent/conversation/router.py` — intent classifier and routing logic

## Key Design
```python
class IntentType(str, Enum):
    TRADE = "trade"           # Execute or discuss a trade
    ANALYZE = "analyze"       # Market analysis request
    PORTFOLIO = "portfolio"   # Portfolio review
    JOURNAL = "journal"       # Journal read/write
    LEARN = "learn"           # Memory/learning query
    PERMISSIONS = "permissions"  # Permission query/request
    STATUS = "status"         # Agent status check
    GENERAL = "general"       # General conversation

class IntentRouter:
    def classify(self, message: str) -> IntentType:
        """Classify user intent from message text."""

    def get_handler(self, intent: IntentType) -> Callable:
        """Return the handler function for the given intent."""

    def route(self, message: str) -> tuple[IntentType, Callable]:
        """Classify and return (intent, handler) pair."""
```

## Acceptance Criteria
- [ ] Router classifies intents from natural language messages
- [ ] Supports slash commands (`/trade`, `/analyze`, etc.) as explicit overrides
- [ ] Falls back to `GENERAL` for unrecognized intents
- [ ] Handler registry is extensible (new handlers can be registered)
- [ ] Classification uses keyword matching for V1 (LLM classification deferred to later)

## Dependencies
- Task 05 (session manager for context)

## Agent Instructions
1. Use keyword matching + regex for V1 classification (fast, no LLM call)
2. Slash commands take priority over NLP classification
3. Make the handler registry a dict so new intent types can be added
4. Each handler signature: `async def handler(session, message, **kwargs) -> str`

## Estimated Complexity
Low — keyword-based routing with extensible handler registry.
