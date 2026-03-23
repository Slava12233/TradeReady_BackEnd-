---
name: correlation_log_returns
description: Log-return Pearson correlation on linearly-growing price series gives near-zero r — use shared-shock series for reliable high-correlation tests
type: feedback
---

Linear price series (e.g. `[40000, 40200, 40400, ...]`) produce nearly-constant log-returns (all ≈ 0.005). Pearson r on near-constant series is undefined or numerically noisy — typically close to 0, NOT close to 1.

**Why:** The variance of returns from a linear trend is dominated by rounding noise, so the covariance is near zero and r collapses.

**How to apply:** When writing tests that need highly-correlated price series, generate prices from **shared random shocks**:

```python
import math, random
random.seed(1)
shocks = [random.choice([-0.03, -0.02, 0.01, 0.02, 0.03]) for _ in range(25)]
btc_closes: list[float] = [40000.0]
eth_closes: list[float] = [2000.0]
for s in shocks:
    btc_closes.append(btc_closes[-1] * math.exp(s + random.gauss(0, 0.0005)))
    eth_closes.append(eth_closes[-1] * math.exp(s + random.gauss(0, 0.0005)))
```

This gives log-return r > 0.99 reliably.  For constant series (r = 1.0 exact), use alternating factors like `[1.05, 0.97, 1.05, 0.97, ...]` applied via `price *= factor` — the resulting log-returns are `[ln(1.05), ln(0.97), ...]`, which have real variance.
