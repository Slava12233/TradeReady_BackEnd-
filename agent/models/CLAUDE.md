# agent/models — Pydantic Output Models

<!-- last-updated: 2026-03-20 -->

> Pydantic v2 output models that serve as `output_type` contracts for Pydantic AI agents throughout the testing workflows.

## What This Module Does

Defines the six structured data models used to capture LLM outputs and workflow results. All models use `ConfigDict(frozen=True)` so instances are immutable and hashable, making them safe to pass as `output_type` values to Pydantic AI agents. Price and monetary fields use `str` to avoid float precision loss in JSON serialisation.

## Key Files

| File | Purpose |
|------|---------|
| `trade_signal.py` | `SignalType` enum and `TradeSignal` — LLM trade decision |
| `analysis.py` | `MarketAnalysis` and `BacktestAnalysis` — LLM analysis outputs |
| `report.py` | `WorkflowResult` and `PlatformValidationReport` — workflow summaries |
| `__init__.py` | Re-exports all 6 public names from a single import path |

## Public API / Key Classes

### `SignalType` (`trade_signal.py`)

`str`-enum with three members. Inherits from `str` so values serialise as plain JSON strings without extra coercion.

| Member | Value |
|--------|-------|
| `BUY` | `"buy"` |
| `SELL` | `"sell"` |
| `HOLD` | `"hold"` |

### `TradeSignal` (`trade_signal.py`)

Structured trade decision produced by trading agents.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `symbol` | `str` | required | e.g. `"BTCUSDT"` |
| `signal` | `SignalType` | required | accepts string coercion from `"buy"/"sell"/"hold"` |
| `confidence` | `float` | `0.0 ≤ x ≤ 1.0` | below 0.5 → trade is skipped in trading workflow |
| `quantity_pct` | `float` | `0.01 ≤ x ≤ 0.10` | fraction of equity; capped by `max_trade_pct` in workflow |
| `reasoning` | `str` | required | human-readable explanation of the decision |
| `risk_notes` | `str` | required | adverse scenarios that could invalidate the signal |

### `MarketAnalysis` (`analysis.py`)

Structured market conditions for a single trading pair.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `symbol` | `str` | required | trading pair analysed |
| `trend` | `str` | required | `"bullish"`, `"bearish"`, or `"neutral"` |
| `support_level` | `str` | required | price as string — avoids float precision loss |
| `resistance_level` | `str` | required | price as string — avoids float precision loss |
| `indicators` | `dict` | defaults to `{}` | keyed by indicator name; values may be float, str, or nested dict |
| `summary` | `str` | required | plain-language synthesis |

### `BacktestAnalysis` (`analysis.py`)

Structured analysis of a completed backtest session.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `session_id` | `str` | required | platform-assigned UUID |
| `sharpe_ratio` | `float` | required | dimensionless ratio; float is appropriate here |
| `max_drawdown` | `float` | `0.0 ≤ x ≤ 1.0` | peak-to-trough equity decline as fraction |
| `win_rate` | `float` | `0.0 ≤ x ≤ 1.0` | fraction of profitable trades |
| `total_trades` | `int` | `≥ 0` | total round-trip trades |
| `pnl` | `str` | required | realised PnL as string — preserves Decimal precision |
| `improvement_plan` | `list[str]` | defaults to `[]` | ordered concrete improvement actions |

### `WorkflowResult` (`report.py`)

Summary of a single test workflow execution. Every workflow runner returns exactly one of these.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `workflow_name` | `str` | required | e.g. `"smoke_test"`, `"trading_workflow"` |
| `status` | `str` | pattern `^(pass\|fail\|partial)$` | overall outcome |
| `steps_completed` | `int` | `≥ 0` | steps that finished successfully |
| `steps_total` | `int` | `≥ 0` | total steps defined for the workflow |
| `findings` | `list[str]` | defaults to `[]` | informational observations |
| `bugs_found` | `list[str]` | defaults to `[]` | confirmed bugs or unexpected errors |
| `suggestions` | `list[str]` | defaults to `[]` | improvement ideas |
| `metrics` | `dict` | defaults to `{}` | arbitrary JSON-serialisable performance data |

### `PlatformValidationReport` (`report.py`)

Top-level report for a full multi-workflow test session. Written to disk as JSON by `agent.main all`.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `session_id` | `str` | required | unique identifier for the session |
| `model_used` | `str` | required | OpenRouter model string |
| `workflows_run` | `list[WorkflowResult]` | defaults to `[]` | ordered results per workflow |
| `platform_health` | `str` | pattern `^(healthy\|degraded\|broken)$` | top-level verdict |
| `summary` | `str` | required | human-readable narrative |

## Patterns

- All models use `ConfigDict(frozen=True)` — instances are immutable after creation; field assignment raises `ValidationError`.
- Price and monetary values use `str` (not `float`) to avoid JSON floating-point precision loss. Convert to `Decimal` before using in arithmetic.
- Ratio and percentage fields (`sharpe_ratio`, `max_drawdown`, `win_rate`, `confidence`, `quantity_pct`) use `float` because they are dimensionless or already bounded.
- All models accept `model_dump()` → `model_validate()` round-trips cleanly; this is how they are saved and loaded from JSON report files.
- The `signal` field on `TradeSignal` accepts plain string coercion (`"buy"` → `SignalType.BUY`) because Pydantic AI serialises tool outputs as JSON strings before passing them as structured output.

## Gotchas

- `indicators` on `MarketAnalysis` is typed as `dict` (not `dict[str, Any]`) for compatibility with Pydantic AI output parsing. Nested dicts are valid values (e.g. a MACD sub-dict).
- `pnl` on `BacktestAnalysis` is `str`, not `Decimal`. Callers must convert before arithmetic. This is intentional — JSON cannot represent `Decimal` natively.
- `platform_health` validates against a regex pattern (`healthy|degraded|broken`). Passing `"ok"` or `"good"` raises `ValidationError`.
- `status` on `WorkflowResult` validates against a regex pattern (`pass|fail|partial`). Any other value raises `ValidationError`.

## Recent Changes

- `2026-03-20` — Initial CLAUDE.md created.
