---
task_id: 05
title: "Conversation session manager"
agent: "backend-developer"
phase: 1
depends_on: [3]
status: "pending"
priority: "high"
files: ["agent/conversation/__init__.py", "agent/conversation/session.py"]
---

# Task 05: Conversation session manager

## Assigned Agent: `backend-developer`

## Objective
Create the `AgentSession` class that manages a single conversation session: creation, message appending, context building, and persistence.

## Files to Create
- `agent/conversation/__init__.py` — export public classes
- `agent/conversation/session.py` — `AgentSession` class

## Key Design
```python
class AgentSession:
    """Manages a single conversation session with the agent."""

    def __init__(self, agent_id: str, session_id: str | None = None):
        ...

    async def start(self) -> None:
        """Create or resume a session."""

    async def add_message(self, role: str, content: str, tool_calls=None, tool_results=None) -> None:
        """Append a message to the session history."""

    async def get_context(self, max_tokens: int = 8000) -> list[dict]:
        """Build LLM context from recent messages + relevant memory."""

    async def summarize_and_trim(self) -> None:
        """Summarize older messages when context window is too large."""

    async def end(self) -> None:
        """Close the session, generate summary."""

    @property
    def is_active(self) -> bool: ...
```

## Acceptance Criteria
- [ ] `AgentSession` can create new sessions or resume existing ones
- [ ] Messages are persisted to DB via `agent_message_repo`
- [ ] `get_context()` returns messages formatted for LLM API
- [ ] `summarize_and_trim()` compresses old messages into a summary
- [ ] Session tracks token usage
- [ ] Proper error handling for DB failures

## Dependencies
- Task 03 (repos for sessions and messages)

## Agent Instructions
1. Read `agent/CLAUDE.md` for agent package conventions
2. Read `agent/config.py` for configuration patterns
3. Use dependency injection for repos (pass session factory or repos)
4. Context building: keep last N messages verbatim, summarize earlier ones
5. Follow the Pydantic AI patterns already in `agent/workflows/`

## Estimated Complexity
Medium — core session management with context window logic.
