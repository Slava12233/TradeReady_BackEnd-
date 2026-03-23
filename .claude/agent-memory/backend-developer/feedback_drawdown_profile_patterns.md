---
name: drawdown_profile_patterns
description: Patterns and gotchas from implementing DrawdownProfile in agent/strategies/risk/ (Task 17)
type: feedback
---

Use `frozen=True` dataclasses for immutable config primitives like `DrawdownTier` and `DrawdownProfile`.
Sorting happens in `__post_init__` via `object.__setattr__` because the dataclass is frozen.

**Why:** Frozen dataclasses prevent accidental mutation of profile config mid-run. The sentinel base tier (threshold=0.0) must always exist for `scale_factor()` to return a valid value without a fallback.

**How to apply:** Validate presence of a 0.0-threshold base tier in `__post_init__`. Use `object.__setattr__` to set attributes on frozen dataclasses.

When adding a non-Pydantic type (e.g. a frozen dataclass) as a field on a `BaseSettings` class, set `arbitrary_types_allowed=True` in `SettingsConfigDict`. Use `exclude=True` on the field to prevent pydantic-settings from trying to read it from env vars.

**Why:** `SettingsConfigDict` in pydantic-settings requires `arbitrary_types_allowed` for any non-Pydantic type field. Without `exclude=True`, it will try to cast the env var string to the dataclass type and fail.

**How to apply:** Always pair `arbitrary_types_allowed=True` with `exclude=True` on programmatic-only fields in `BaseSettings` subclasses.

The `scale_factor` field in `RiskAssessment` has a special HALT override: when verdict is `"HALT"`, force `scale_factor=0.0` regardless of what the DrawdownProfile would return. This prevents downstream consumers from accidentally sizing any position.

**Why:** HALT means no new trades. A non-zero scale_factor would mislead callers into thinking partial sizing is acceptable.

**How to apply:** Check verdict before calling `profile.scale_factor()`. If verdict == "HALT", set scale_factor=0.0 directly.
