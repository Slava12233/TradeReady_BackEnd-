---
task_id: 34
title: "Pydantic output models for agent ecosystem"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "medium"
files: ["agent/models/ecosystem.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 34: Pydantic output models for agent ecosystem

## Assigned Agent: `backend-developer`

## Objective
Define all Pydantic v2 models used across the agent ecosystem: trade decisions, journal entries, memory objects, permissions, budget status, strategy performance, etc.

## Files to Create
- `agent/models/ecosystem.py` — all ecosystem output models

## Models to Define
- `TradeDecision` — decision with reasoning, signals, confidence
- `TradeReflection` — post-trade analysis
- `PortfolioReview` — portfolio health assessment
- `Opportunity` — trading opportunity with entry/exit suggestions
- `JournalEntry` — journal entry with market context
- `FeedbackEntry` — platform feedback/feature request
- `BudgetCheckResult` — budget check response (allowed/denied + reason)
- `BudgetStatus` — current budget utilization
- `EnforcementResult` — permission check result
- `AuditEntry` — permission audit log entry
- `DegradationAlert` — strategy degradation notification
- `Adjustment` — suggested strategy adjustment
- `StrategyPerformance` — rolling strategy stats
- `StrategyComparison` — head-to-head strategy comparison
- `ABTestResult` — A/B test evaluation result
- `TradingCycleResult` — result of one trading loop tick
- `ExecutionResult` — result of trade execution
- `PositionAction` — recommended position action (hold/exit)
- `HealthStatus` — agent server health

## Acceptance Criteria
- [ ] All models use Pydantic v2 `BaseModel`
- [ ] `Decimal` for all money/price fields (never `float`)
- [ ] Proper type hints and field descriptions
- [ ] `model_config` with `json_schema_extra` examples where helpful
- [ ] Models follow patterns in `agent/models/analysis.py` and `agent/models/trade_signal.py`

## Dependencies
None — models are independent of implementation.

## Agent Instructions
1. Read `agent/models/CLAUDE.md` and existing models
2. Group related models together with comments
3. Use `from decimal import Decimal` consistently
4. Add `Field(description=...)` for non-obvious fields
5. These models will be used by tasks 16-17, 21-23, 26-30

## Estimated Complexity
Medium — many models but straightforward Pydantic definitions.
