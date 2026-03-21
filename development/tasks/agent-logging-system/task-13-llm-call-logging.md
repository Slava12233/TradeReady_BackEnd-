---
task_id: 13
title: "Add LLM call logging with token counts and cost estimates"
type: task
agent: "backend-developer"
phase: 2
depends_on: [1]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/conversation/session.py", "agent/trading/journal.py", "agent/workflows/trading_workflow.py", "agent/workflows/backtest_workflow.py", "agent/workflows/strategy_workflow.py"]
tags:
  - task
  - agent
  - logging
---

# Task 13: Add LLM Call Logging

## Assigned Agent: `backend-developer`

## Objective
Add structured logging for every LLM call the agent makes, capturing model name, purpose, token counts, latency, and cost estimates.

## Files to Modify
- `agent/conversation/session.py` — session summarization LLM calls
- `agent/trading/journal.py` — trade reflection LLM calls
- `agent/workflows/trading_workflow.py` — trade analysis LLM calls
- `agent/workflows/backtest_workflow.py` — backtest analysis LLM calls
- `agent/workflows/strategy_workflow.py` — strategy review LLM calls

## Implementation Pattern

For each LLM call location:
1. Wrap the call with `time.monotonic()` timing
2. After the call, log:
```python
logger.info(
    "agent.llm.completed",
    model=model_name,
    purpose="trade_reflection",  # unique per call site
    input_tokens=response.usage.input_tokens if hasattr(response, 'usage') else None,
    output_tokens=response.usage.output_tokens if hasattr(response, 'usage') else None,
    latency_ms=round((time.monotonic() - start) * 1000, 2),
    cost_estimate_usd=_estimate_cost(model, input_tokens, output_tokens),
)
```
3. On LLM failure, log at ERROR:
```python
logger.error("agent.llm.failed", model=model_name, purpose=purpose, error=str(exc))
```

## Cost Estimation Helper
Add a simple cost lookup function (approximate per-token prices):
```python
_MODEL_COSTS = {
    "anthropic/claude-sonnet": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "google/gemini-2.0-flash": {"input": 0.1 / 1_000_000, "output": 0.4 / 1_000_000},
}
```

## Purpose Values
- `"session_summarization"` — session.py
- `"trade_reflection"` — journal.py
- `"trade_analysis"` — trading_workflow.py
- `"backtest_analysis"` — backtest_workflow.py
- `"strategy_review"` — strategy_workflow.py

## Acceptance Criteria
- [ ] Every LLM call site produces a log line with model, purpose, tokens, latency, cost
- [ ] Failed LLM calls logged at ERROR with error message
- [ ] Cost estimates are approximate but reasonable
- [ ] No behavioral changes to existing LLM call logic
- [ ] `ruff check` passes on all modified files

## Agent Instructions
- Read each file to find where LLM calls are made (look for `httpx.post`, `openrouter`, or Pydantic AI agent calls)
- Token usage may not always be available (e.g., when using Pydantic AI's `agent.run()`) — handle None gracefully
- The cost helper can go in `agent/logging_middleware.py` or `agent/logging.py`

## Estimated Complexity
Medium — 5 files, each with different LLM call patterns
