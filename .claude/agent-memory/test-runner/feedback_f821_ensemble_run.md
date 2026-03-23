---
name: F821 RiskMiddleware missing from lazy import in ensemble/run.py
description: ensemble/run.py had F821 undefined name — RiskMiddleware was used but not included in the lazy import block; fixed 2026-03-22
type: feedback
---

`agent/strategies/ensemble/run.py` method `_build_risk_middleware()` used `RiskMiddleware` at line 663 but the lazy import block at line 652 only imported `DynamicSizer`, `RiskAgent`, `RiskConfig`, `SizerConfig`, `VetoPipeline` — missing `RiskMiddleware`.

**Why:** The fix was to add `RiskMiddleware` to the lazy `from agent.strategies.risk import (...)` block. `RiskMiddleware` is exported from `agent.strategies.risk.__init__` so the import resolves correctly.

**How to apply:** When reviewing ensemble/run.py lazy imports, ensure all names used in the function body are included in the lazy import block. Ruff F821 (undefined name) catches this at lint time but only when ruff can statically resolve the missing name.
