---
task_id: 17
title: "Risk agent core"
agent: "backend-developer"
phase: D
depends_on: []
status: "completed"
priority: "medium"
files: ["agent/strategies/risk/__init__.py", "agent/strategies/risk/risk_agent.py"]
---

# Task 17: Risk agent core

## Assigned Agent: `backend-developer`

## Objective
Build the risk monitoring agent that tracks portfolio-level exposure, correlation, and drawdown. This agent reads portfolio state and outputs risk assessments.

## Files to Create
- `agent/strategies/risk/__init__.py`
- `agent/strategies/risk/risk_agent.py`:
  - `RiskAgent` class:
    - `__init__(config: RiskConfig, sdk_client)` — config with thresholds
    - `assess(portfolio, positions, recent_pnl)` → `RiskAssessment`:
      - `total_exposure_pct`: float (sum positions / equity)
      - `max_single_position_pct`: float
      - `drawdown_pct`: float (from peak equity)
      - `correlation_risk`: str ("low", "medium", "high") — based on # of same-sector positions
      - `verdict`: str ("OK", "REDUCE", "HALT")
      - `action`: str | None — e.g., "close position in SOLUSDT" or None
    - `check_trade(proposed_signal, portfolio)` → `TradeApproval`:
      - `approved`: bool
      - `adjusted_size_pct`: float (may reduce from proposed)
      - `reason`: str
  - `RiskConfig(BaseSettings)`:
    - max_portfolio_exposure: 0.30 (30% of equity in positions)
    - max_single_position: 0.10 (10%)
    - max_drawdown_trigger: 0.05 (5% → start reducing)
    - max_correlated_positions: 2 (same sector)
    - daily_loss_halt: 0.03 (3% → halt trading)

## Acceptance Criteria
- [ ] RiskAssessment correctly computes exposure from position data
- [ ] Drawdown computed from peak equity (not starting equity)
- [ ] "REDUCE" triggered when drawdown > 5%
- [ ] "HALT" triggered when daily loss > 3%
- [ ] Trade approval reduces position size when near limits
- [ ] Trade approval vetoes when at max exposure
- [ ] All thresholds are configurable via RiskConfig
- [ ] Uses `Decimal` for all financial calculations

## Dependencies
None — pure logic, uses SDK client for data only.

## Agent Instructions
Read `src/risk/CLAUDE.md` for the platform's built-in risk manager (8-step validation). This Risk Agent adds portfolio-level checks ON TOP of the platform's per-order checks. Don't duplicate what the platform already does.

## Estimated Complexity
Medium — financial logic with careful threshold handling.
