---
name: kelly_hybrid_sizing_patterns
description: Patterns and conventions discovered while implementing KellyFractionalSizer and HybridSizer in agent/strategies/risk/sizing.py
type: project
---

Task 16 added Half-Kelly and ATR-adjusted position sizing to `agent/strategies/risk/sizing.py`.

**Why:** The original `DynamicSizer` uses a volatility/drawdown adjustment on a static base_size_pct but has no awareness of the statistical edge of a strategy. Kelly criterion addresses this directly.

**Key design decisions:**
- `SizingMethod` is a `str, Enum` (not a plain enum) so it compares equal to plain strings — consistent with other enum patterns in the project (e.g. `SignalType`).
- `calculate_kelly_fraction()` is a `@staticmethod` on `KellyFractionalSizer` so `HybridSizer` can reuse it without constructing a `KellyFractionalSizer` instance.
- Zero Kelly (no edge) returns `0.0` — intentionally bypasses `min_trade_pct` to signal "do not trade". This is different from hitting the floor clamp; callers must check `result == 0.0` to detect this case.
- `HybridConfig` and `KellyConfig` use `env_prefix="HYBRID_"` and `env_prefix="KELLY_"` respectively, following the existing `SIZER_`, `RL_`, `EVO_`, `ENSEMBLE_` pattern.
- All new config classes extend `pydantic_settings.BaseSettings` with `SettingsConfigDict(extra="ignore")`.

**How to apply:** When adding new sizing strategies, follow the same pattern: separate `Config` (`BaseSettings`), class with `__init__(config | None)`, return `float`, use `Decimal` internally, always quantize with `_D4`, log via structlog.
