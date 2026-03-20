# agent/strategies/risk/ — Portfolio Risk Management Overlay

<!-- last-updated: 2026-03-20 -->

> Portfolio-level risk checks that complement the platform's built-in per-order risk manager, operating at aggregate exposure level to gate and resize trade signals before execution.

## What This Module Does

The `risk/` sub-package adds an agent-side risk layer on top of the platform's built-in `src/risk/manager.py`. While the platform enforces per-order hard limits (max position size, daily loss circuit breaker), the risk overlay here operates at the portfolio level: it assesses aggregate drawdown and daily PnL, vetoes trades that would push the portfolio into dangerous territory, and dynamically resizes positions based on current volatility and drawdown depth.

The `RiskMiddleware` class wires all three components (`RiskAgent`, `VetoPipeline`, `DynamicSizer`) into a single async callable. Callers do not need to instantiate or sequence the individual components.

107 unit tests cover all components.

## Key Files

| File | Purpose |
|------|---------|
| `risk_agent.py` | `RiskAgent`, `RiskConfig`, `RiskAssessment`, `TradeApproval` — assess portfolio state; gate proposed trades. |
| `veto.py` | `VetoPipeline`, `VetoDecision` — 6-gate sequential pipeline from HALT check to APPROVED. |
| `sizing.py` | `DynamicSizer`, `SizerConfig` — volatility- and drawdown-adjusted position sizing. |
| `middleware.py` | `RiskMiddleware`, `ExecutionDecision` — single async entry point wiring all three components. |

## Public API

```python
from agent.strategies.risk.risk_agent import RiskAgent, RiskConfig, RiskAssessment, TradeApproval
from agent.strategies.risk.veto import VetoPipeline, VetoDecision
from agent.strategies.risk.sizing import DynamicSizer, SizerConfig
from agent.strategies.risk.middleware import RiskMiddleware, ExecutionDecision
```

### `RiskAgent` (`risk_agent.py`)

| Method | Returns | Description |
|--------|---------|-------------|
| `assess(portfolio, positions, daily_pnl)` | `RiskAssessment` | Returns `"OK"`, `"REDUCE"`, or `"HALT"` based on portfolio metrics |
| `check_trade(signal, assessment)` | `TradeApproval` | Pre-trade check combining assessment verdict with signal-level size limits |

Assessment verdicts:
- `"HALT"` — daily PnL loss exceeds `daily_loss_halt` threshold (from `RiskConfig`)
- `"REDUCE"` — portfolio drawdown exceeds `max_drawdown_trigger`
- `"OK"` — within acceptable bounds

### `VetoPipeline` (`veto.py`)

Six sequential gates. Short-circuits on the first `VETOED` outcome; `RESIZED` decisions do not short-circuit (all size-reduction factors stack):

| Gate | Condition | Outcome |
|------|-----------|---------|
| 1 | Risk verdict is `HALT` | `VETOED` |
| 2 | Signal confidence < 0.5 | `VETOED` |
| 3 | Exceeds max portfolio exposure | `RESIZED` (reduce to limit) |
| 4 | ≥ 2 existing positions in the same sector | `VETOED` |
| 5 | Recent drawdown > 3% | `RESIZED` (halve position) |
| 6 | All checks passed | `APPROVED` |

`VetoDecision` fields: `verdict` (`"APPROVED"`, `"VETOED"`, `"RESIZED"`), `reason`, `size_factor` (1.0 unless RESIZED).

### `DynamicSizer` (`sizing.py`)

Adjusts base position size from `SizerConfig.base_size_pct` downward based on two factors:

1. **Volatility adjustment** — higher ATR/close → smaller position; formula: `base_size * (target_vol / current_vol)`.
2. **Drawdown adjustment** — linear reduction as drawdown deepens from `drawdown_start` to `drawdown_max`.

Final size = `base_size * volatility_factor * drawdown_factor`, floored at `SizerConfig.min_size_pct`.

### `RiskMiddleware` (`middleware.py`)

4-stage async pipeline per signal:

1. Fetch portfolio state via SDK `get_portfolio()`
2. `RiskAgent.assess()` → `RiskAssessment`
3. `VetoPipeline.evaluate(signal, assessment)` → `VetoDecision`
4. `DynamicSizer.calculate_size(signal, portfolio)` → final size

Returns `ExecutionDecision` (never raises). All errors surfaced in `ExecutionDecision.error`. If `execute=True` is passed, additionally places the order via SDK `place_market_order()`.

```python
middleware = RiskMiddleware(config, sdk_client)
decision = await middleware.process(signal, execute=True)
if decision.approved:
    print(f"Trade placed: {decision.order_id}")
else:
    print(f"Trade vetoed: {decision.veto_reason}")
```

## Patterns

- **Non-crashing middleware** — `RiskMiddleware.process()` wraps every stage in try/except; callers always receive a valid `ExecutionDecision`.
- **`RESIZED` does not short-circuit** — a trade that triggers gates 3 and 5 gets reduced by both size factors sequentially. This is intentional conservative behaviour.
- **No standalone CLI** — `risk/` is used programmatically from `ensemble/run.py` and any strategy's trading loop. There is no CLI entry point.

## Gotchas

- **`RiskMiddleware` does not close the SDK client.** The shared `AsyncAgentExchangeClient` passed to `RiskMiddleware` is not closed inside `process()`. The caller is responsible for cleanup.
- **`VetoPipeline` sector concentration check uses the symbol prefix.** Sector is inferred from the trading pair symbol (e.g., `"BTC"` from `"BTCUSDT"`). Symbols with the same 3-letter prefix are treated as the same sector. This can produce false positives for multi-exchange strategies with unusual symbol conventions.
- **`DynamicSizer` requires volatility data.** If `current_vol` is zero or NaN (insufficient candle history), the sizer falls back to `base_size_pct`. Always warm up with at least 14 candles before enabling volatility adjustment.
- **This layer is separate from the platform's `src/risk/manager.py`.** The platform's risk manager enforces hard limits on every order at the API level. This overlay operates at a higher level (portfolio strategy) and is not a replacement for the platform's controls.

## Recent Changes

- `2026-03-20` — Initial CLAUDE.md created.
