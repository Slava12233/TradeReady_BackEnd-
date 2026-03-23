---
name: feedback_celery_task_patterns
description: Patterns for adding new tasks to src/tasks/agent_analytics.py and wiring into Celery beat schedule (Task 30)
type: feedback
---

Ruff rule N806 rejects UPPER_SNAKE_CASE constants defined inside a function body (`_SETTLED_STATUSES`). Use lowercase names for local frozensets inside async task bodies (`settled_statuses`).

**Why:** N806 treats any uppercase variable assignment inside a function as a violation even when it reads as a constant. Ruff does not have a way to declare "this is an intentional in-function constant".

**How to apply:** Inside async task body functions, define lookup sets with lowercase names. Top-level module constants can remain UPPER_SNAKE_CASE.

---

When testing Celery analytics tasks that use two nested `async with session_factory()` blocks (outer for agent list, inner for per-agent work), build two separate `(session, ctx)` pairs and pass them as a `side_effect` list to `combined_factory`.

**Why:** A single `mock_factory` whose `return_value` is a single ctx will give the same session to both the outer and inner `async with` calls, causing execute side_effect lists to interleave incorrectly.

**How to apply:** Always split outer/inner sessions when the task function opens two separate `async with session_factory()` blocks. Pattern: `combined_factory = MagicMock(side_effect=[outer_ctx, inner_ctx])`.

---

The beat schedule entry name uses hyphen-separated lowercase (e.g., `"settle-agent-decisions"`), and the task name string uses dot-separated module path (e.g., `"src.tasks.agent_analytics.settle_agent_decisions"`). Keep these two consistently different forms.
