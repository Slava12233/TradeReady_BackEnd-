---
name: gym_test_patterns
description: Confirmed test patterns for tradeready-gym rewards and RLConfig in this codebase
type: feedback
---

Tests for gym reward functions live in `tradeready-gym/tests/`. The existing file is `test_gymnasium_compliance.py`; new dedicated reward test files are welcome (e.g. `test_composite_reward.py`).

The `_mock_api_call` pattern in `test_gymnasium_compliance.py` is the canonical way to mock the backtest API responses. Key mock paths:
- `tradeready_gym.envs.base_trading_env.httpx.Client` — mock HTTP transport
- `tradeready_gym.envs.base_trading_env.TrainingTracker` — mock training tracker (prevents HTTP calls to training API)

**Note:** `test_gymnasium_compliance.py` has a pre-existing bug: `TrainingTracker` is used in `TestTrainingTracker` but is never imported at module level. Two tests fail with `NameError`. Do not fix this unless explicitly asked — it is pre-existing.

For `RLConfig` validation tests: use `from pydantic import ValidationError` and assert `pytest.raises(ValidationError)` for invalid field values.

`asyncio_mode = "auto"` is set in `tradeready-gym/pyproject.toml` — no `@pytest.mark.asyncio` decorator needed.

**Why:** Learned from Task 10 (composite reward implementation). Patterns are consistent across all reward test classes.

**How to apply:** When writing new gym reward tests, create a dedicated `tests/test_<reward_name>_reward.py` file. Use isolated single-component `CompositeReward`-style instances (set other weights to 0.0) to test each sub-component independently.
