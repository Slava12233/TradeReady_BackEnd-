---
task_id: 30
title: "Strategy A/B testing framework"
agent: "ml-engineer"
phase: 2
depends_on: [29]
status: "pending"
priority: "medium"
files: ["agent/trading/ab_testing.py"]
---

# Task 30: Strategy A/B testing framework

## Assigned Agent: `ml-engineer`

## Objective
Create an A/B testing framework that allows the agent to run two strategy variants in parallel and promote the winner automatically.

## Files to Create
- `agent/trading/ab_testing.py` — `ABTestRunner` class

## Key Design
```python
class ABTest(BaseModel):
    id: str
    agent_id: str
    strategy_name: str
    variant_a: dict  # strategy params
    variant_b: dict  # modified params
    min_trades: int = 50
    status: str  # "active", "completed", "cancelled"
    winner: str | None  # "a" or "b"
    started_at: datetime
    completed_at: datetime | None

class ABTestRunner:
    async def create_test(
        self,
        agent_id: str,
        strategy_name: str,
        variant_a_params: dict,
        variant_b_params: dict,
        min_trades: int = 50,
    ) -> ABTest: ...

    async def record_result(
        self,
        test_id: str,
        variant: str,
        signal: TradingSignal,
        outcome_pnl: Decimal,
    ) -> None: ...

    async def evaluate(self, test_id: str) -> ABTestResult:
        """
        Compare variants after min_trades:
        - Sharpe ratio comparison
        - Win rate comparison
        - Statistical significance test (t-test)
        """

    async def promote_winner(self, test_id: str) -> None:
        """Apply winning variant's parameters to the live strategy."""

    async def get_active_tests(self, agent_id: str) -> list[ABTest]: ...
```

## Acceptance Criteria
- [ ] A/B tests track results per variant
- [ ] Evaluation uses statistical significance (t-test or similar)
- [ ] Winner not declared until `min_trades` reached for both variants
- [ ] `promote_winner` updates strategy parameters via strategy registry
- [ ] Tests persist to DB (can use `agent_performance` or a JSONB field)
- [ ] Only one A/B test per strategy at a time

## Dependencies
- Task 29 (strategy manager)

## Agent Instructions
1. Read `src/strategies/CLAUDE.md` for strategy parameter patterns
2. Use `scipy.stats.ttest_ind` for significance testing
3. A/B test allocation: alternate trades between variants (round-robin)
4. Store A/B test metadata in `agent_journal` with type "ab_test"
5. Promotion should update strategy config, not create a new strategy

## Estimated Complexity
Medium — A/B testing with statistical evaluation and automated promotion.
