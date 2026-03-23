---
name: signal_volume_filter_pattern
description: How the volume confirmation filter is structured in SignalGenerator and tested in isolation
type: feedback
---

Volume filter in `SignalGenerator` is implemented as two static/instance methods appended after the ensemble step in `generate()`:

1. `_compute_volume_ratio(candles)` — pure static, returns `float | None`. Uses a rolling window (`_VOLUME_LOOKBACK = 20`) on the candle list; excludes the final candle from the baseline average, then computes `latest_vol / mean(rest)`. Returns `None` on empty/single candle lists, all-zero averages, and unparseable volume fields. Never raises.

2. `_apply_volume_filter(signals, candles_by_symbol)` — instance method iterating over signals. HOLD signals pass through unchanged (never rejected by volume). Non-HOLD signals whose ratio is `< _VOLUME_MIN_RATIO` (0.5) are replaced with `_hold_signal(reason="low_volume")`. When no candle data is available for a symbol (ratio returns None), the signal is kept — fail-open is the correct default for data absence.

**Why:** Prevents the ensemble from acting on low-volume candles where spread and slippage risk are elevated. 50% threshold rejects only genuinely thin candles while allowing normal intraday volume variance.

**How to apply:** Any future `SignalGenerator` filter additions should follow the same two-method pattern (static compute + instance apply) and insert as a new numbered step at the end of `generate()`. Each step should log a structured message when it rejects a signal.

The volume constants (`_VOLUME_LOOKBACK`, `_VOLUME_MIN_RATIO`) are exported from the module so tests can import them for sanity assertions without hardcoding magic numbers.
