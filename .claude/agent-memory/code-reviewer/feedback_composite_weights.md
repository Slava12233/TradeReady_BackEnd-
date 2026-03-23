---
name: composite_weight_sum_validator
description: Pydantic-settings configs with multi-field weight sets need a model_validator enforcing sum=1.0
type: feedback
---

When a pydantic-settings `BaseSettings` class has multiple `float` fields that must sum to a fixed value (e.g., reward component weights summing to 1.0), add a `@model_validator(mode="after")` to enforce the constraint at config load time.

**Why:** `CompositeReward.__init__()` already validates the sum, but this only fires at gym construction time (deep in training), far from the misconfiguration site. A validator on `RLConfig` catches it immediately when the config is loaded from `.env`.

**How to apply:** Found in Task 10 (`agent/strategies/rl/config.py` — composite weight fields lack sum validator). Pattern: `RL_COMPOSITE_PNL_WEIGHT` in `.env` can be misconfigured without any error until training starts.
