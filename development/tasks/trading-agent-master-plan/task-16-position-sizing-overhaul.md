---
task_id: 16
title: "Implement position sizing overhaul (Half-Kelly + ATR)"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/risk/sizing.py", "agent/models/config.py"]
tags:
  - task
  - risk
  - trading
---

# Task 16: Position sizing overhaul

## Assigned Agent: `backend-developer`

## Objective
Implement Half-Kelly and ATR-based position sizing methods alongside the existing `DynamicSizer`. Add configurable `SizerConfig.method` field supporting `"atr"`, `"kelly_half"`, `"kelly_quarter"`, and `"hybrid"`.

## Key Implementation
```python
# Half-Kelly
kelly_fraction = (win_rate * avg_win_loss_ratio - (1 - win_rate)) / avg_win_loss_ratio
position_pct = kelly_fraction / 2  # or /4 for conservative
position_pct = clamp(position_pct, 0.03, 0.10)

# ATR-based
position_size = risk_amount / (ATR * atr_multiple)

# Hybrid: ATR-adjusted Kelly
position_pct = kelly_pct * (target_vol / current_vol)
```

## Files to Modify
- `agent/strategies/risk/sizing.py` — add `KellyFractionalSizer`, `HybridSizer`
- `agent/models/config.py` — increase `max_trade_pct` to 0.10

## Acceptance Criteria
- [ ] `KellyFractionalSizer` class with configurable fraction (1/2, 1/4)
- [ ] `HybridSizer` combining Kelly + ATR volatility adjustment
- [ ] `SizerConfig.method` field selects sizing strategy
- [ ] `max_trade_pct` configurable per agent (default 0.10 for aggressive)
- [ ] Unit tests for each sizing method

## Estimated Complexity
Medium — new classes following existing pattern.
