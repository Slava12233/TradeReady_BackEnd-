---
task_id: 7
title: "Output models (TradeSignal, Analysis, Report)"
agent: "backend-developer"
phase: 3
depends_on: [1]
status: "completed"
priority: "high"
files:
  - "agent/models/trade_signal.py"
  - "agent/models/analysis.py"
  - "agent/models/report.py"
  - "agent/models/__init__.py"
---

# Task 7: Output models (TradeSignal, Analysis, Report)

## Assigned Agent: `backend-developer`

## Objective
Implement Pydantic v2 output models that the agent uses for structured responses. These models serve as `output_type` for Pydantic AI agents, ensuring the LLM returns well-typed data.

## Files to Create

### `agent/models/trade_signal.py`
- `SignalType(str, Enum)` — BUY, SELL, HOLD
- `TradeSignal(BaseModel)` — symbol, signal, confidence (0-1), quantity_pct (0.01-0.10), reasoning, risk_notes

### `agent/models/analysis.py`
- `MarketAnalysis(BaseModel)` — symbol, trend (bullish/bearish/neutral), support_level, resistance_level, indicators (dict), summary
- `BacktestAnalysis(BaseModel)` — session_id, sharpe_ratio, max_drawdown, win_rate, total_trades, pnl, improvement_plan (list[str])

### `agent/models/report.py`
- `WorkflowResult(BaseModel)` — workflow_name, status (pass/fail/partial), steps_completed, steps_total, findings (list), bugs_found (list), suggestions (list), metrics (dict)
- `PlatformValidationReport(BaseModel)` — session_id, model_used, workflows_run (list[WorkflowResult]), platform_health, summary

### `agent/models/__init__.py`
- Re-export all models for convenience: `from agent.models import TradeSignal, WorkflowResult, ...`

## Acceptance Criteria
- [ ] All 6 models defined with proper type hints
- [ ] Models use Pydantic v2 `BaseModel` (not v1)
- [ ] `SignalType` is a proper `str, Enum`
- [ ] All numeric fields use appropriate types (float for ratios, Decimal for prices)
- [ ] `__init__.py` re-exports all models
- [ ] Models are serializable to JSON (required for Pydantic AI `output_type`)

## Dependencies
- Task 1 (package structure must exist)

## Agent Instructions
- Follow the exact model definitions from the plan (Section 3 of agent_plan.md)
- Use `float` for confidence/percentages (these are ratios, not money)
- Use `str` for price values (they come from the platform as strings)
- Add `model_config = ConfigDict(frozen=True)` for immutability where appropriate

## Estimated Complexity
Low — straightforward Pydantic model definitions
