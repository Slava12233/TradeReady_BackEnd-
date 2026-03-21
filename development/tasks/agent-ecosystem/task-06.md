---
task_id: 06
title: "Conversation history and context builder"
type: task
agent: "backend-developer"
phase: 1
depends_on: [5]
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "high"
files: ["agent/conversation/history.py", "agent/conversation/context.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 06: Conversation history and context builder

## Assigned Agent: `backend-developer`

## Objective
Create the history loader and dynamic context builder for the conversation system. The context builder assembles the LLM system prompt from multiple sources.

## Files to Create
- `agent/conversation/history.py` — load/save/search conversation history
- `agent/conversation/context.py` — dynamic system prompt assembly

## Key Design

### history.py
```python
class ConversationHistory:
    async def load_session(self, session_id: str) -> list[Message]: ...
    async def load_recent(self, agent_id: str, limit: int = 50) -> list[Message]: ...
    async def search(self, agent_id: str, query: str) -> list[Message]: ...
    async def get_summary(self, session_id: str) -> str | None: ...
```

### context.py
```python
class ContextBuilder:
    """Assembles the LLM context from multiple sources."""

    async def build(self, agent_id: str, session: AgentSession) -> list[dict]:
        """
        Builds context from:
        1. Base persona (from agent/prompts/system.py)
        2. Current portfolio state (via SDK)
        3. Recent learnings (from memory system)
        4. Active strategy info
        5. Current permissions and budget
        6. Recent conversation messages
        """
```

## Acceptance Criteria
- [ ] `ConversationHistory` can load, paginate, and search messages
- [ ] `ContextBuilder` assembles a complete system prompt dynamically
- [ ] Context includes portfolio state, strategy info, and recent learnings
- [ ] Token counting is approximate but prevents context overflow
- [ ] Graceful degradation when external data unavailable (portfolio API down, etc.)

## Dependencies
- Task 05 (session manager)

## Agent Instructions
1. Read `agent/prompts/system.py` for the existing system prompt
2. Read `agent/tools/sdk_tools.py` for SDK call patterns
3. Context priority: system prompt > portfolio state > recent messages > learnings
4. Use tiktoken or a simple word-based approximation for token counting
5. If a data source fails, include a note in context ("portfolio data unavailable")

## Estimated Complexity
Medium — multiple data sources, token management, error handling.
