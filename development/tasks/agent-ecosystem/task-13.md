---
task_id: 13
title: "Agent server — persistent async process"
agent: "backend-developer"
phase: 1
depends_on: [5, 9]
status: "pending"
priority: "high"
files: ["agent/server.py"]
---

# Task 13: Agent server — persistent async process

## Assigned Agent: `backend-developer`

## Objective
Create the long-running agent server process that replaces the one-shot CLI. This is the central event loop: it listens for input, reasons via LLM, acts via tools, responds, and persists state.

## Files to Create
- `agent/server.py` — `AgentServer` class with async event loop

## Key Design
```python
class AgentServer:
    """Persistent agent process with event loop."""

    def __init__(self, agent_id: str, config: AgentConfig): ...

    async def start(self) -> None:
        """Initialize connections, load state, start event loop."""

    async def stop(self) -> None:
        """Graceful shutdown: save state, close connections."""

    async def process_message(self, message: str, session: AgentSession) -> str:
        """Main reasoning cycle: context → LLM → tools → response → persist."""

    async def health_check(self) -> dict:
        """Return health status for monitoring."""

    async def run_scheduled_task(self, task_name: str) -> None:
        """Execute a scheduled task (e.g., morning market review)."""

    # Internal
    async def _reasoning_loop(self, context: list[dict], message: str) -> str: ...
    async def _persist_state(self) -> None: ...
```

## Acceptance Criteria
- [ ] Server starts, initializes DB session + Redis + memory system
- [ ] `process_message()` uses Pydantic AI agent for LLM reasoning
- [ ] Graceful shutdown saves state and closes connections
- [ ] Health check returns: uptime, active session, last activity, memory stats
- [ ] Auto-restart on crash (via process supervisor or internal try/except)
- [ ] Signal handlers for SIGINT/SIGTERM
- [ ] Integrates with existing `agent/main.py` Pydantic AI setup

## Dependencies
- Task 05 (session manager), Task 09 (memory system)

## Agent Instructions
1. Read `agent/main.py` for existing Pydantic AI agent setup — extend, don't replace
2. Read `agent/config.py` for config patterns
3. The server wraps the existing agent with persistent state management
4. Use `asyncio.Event` for shutdown signaling
5. Health check should be callable via a simple HTTP endpoint or CLI command
6. Scheduled tasks will be triggered by Celery beat (Task 14)

## Estimated Complexity
High — central orchestrator with lifecycle management, error recovery, and state persistence.
