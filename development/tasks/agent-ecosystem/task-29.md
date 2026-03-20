---
task_id: 29
title: "Strategy management — performance monitoring and degradation detection"
agent: "ml-engineer"
phase: 2
depends_on: [26]
status: "pending"
priority: "medium"
files: ["agent/trading/strategy_manager.py"]
---

# Task 29: Strategy management — performance monitoring and degradation detection

## Assigned Agent: `ml-engineer`

## Objective
Create the strategy management system that monitors real-time strategy performance, detects degradation (Sharpe dropping below threshold), and suggests parameter adjustments.

## Files to Create
- `agent/trading/strategy_manager.py` — `StrategyManager` class

## Key Design
```python
class StrategyManager:
    """Monitors and manages trading strategy performance."""

    async def record_strategy_result(
        self,
        agent_id: str,
        strategy_name: str,
        signal: TradingSignal,
        outcome_pnl: Decimal | None = None,
    ) -> None:
        """Record a strategy's signal and its outcome."""

    async def get_performance(
        self,
        agent_id: str,
        strategy_name: str | None = None,
        period: str = "weekly",
    ) -> list[StrategyPerformance]:
        """Get rolling performance stats per strategy."""

    async def detect_degradation(self, agent_id: str) -> list[DegradationAlert]:
        """
        Check each strategy for degradation:
        - Sharpe ratio dropping below 0.5 (configurable)
        - Win rate dropping below 40%
        - Max drawdown exceeding threshold
        - Consecutive losses exceeding N
        """

    async def suggest_adjustments(self, agent_id: str, strategy_name: str) -> list[Adjustment]:
        """
        Analyze recent performance and suggest:
        - Parameter tweaks (e.g., reduce position size)
        - Regime-specific disabling
        - Confidence threshold changes
        """

    async def compare_strategies(self, agent_id: str) -> StrategyComparison:
        """Compare all strategies head-to-head over recent period."""
```

## Acceptance Criteria
- [ ] Performance tracked per strategy per period (daily/weekly/monthly)
- [ ] Degradation detection with configurable thresholds
- [ ] Alerts generated when thresholds breached
- [ ] Suggestions based on statistical analysis of recent trades
- [ ] Strategy comparison with ranking
- [ ] Uses `agent_performance` table for persistence
- [ ] Integrates with existing strategy code in `agent/strategies/`

## Dependencies
- Task 26 (trading loop provides strategy results)

## Agent Instructions
1. Read `agent/strategies/CLAUDE.md` for strategy architecture
2. Read `src/metrics/CLAUDE.md` for existing metrics calculation
3. Use the unified metrics calculator for Sharpe, drawdown, win rate
4. Degradation detection should use a rolling window (configurable, default 50 trades)
5. Suggestions should be conservative (reduce exposure, not radical changes)

## Estimated Complexity
High — statistical monitoring with threshold detection and suggestion engine.
