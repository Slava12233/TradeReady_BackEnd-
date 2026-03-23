---
name: reward_system_architecture
description: Where to register new reward functions and how the reward_type config field links train.py to gym
type: project
---

Reward functions live in `tradeready-gym/tradeready_gym/rewards/`. Each is a subclass of `CustomReward` (in `custom_reward.py`) implementing `compute(prev_equity, curr_equity, info) -> float` and optionally `reset() -> None`.

Three registration points must be updated when adding a new reward:
1. `tradeready_gym/rewards/__init__.py` — import and add to `__all__`
2. `tradeready_gym/__init__.py` — import and add to `__all__` (the top-level package)
3. `agent/strategies/rl/train.py` — add a `case` to `_build_reward()` and add the string to the `--reward` CLI choices
4. `agent/strategies/rl/config.py` — add the string to the `validate_reward_type` validator's `allowed` set

The `info` dict passed to `compute()` matches the backtest API step response. Key fields:
- `info["portfolio"]["starting_balance"]` — string, the episode's starting USDT balance
- `info["portfolio"]["total_equity"]` — string, current total equity
- `info["filled_orders"]` — list, empty when the agent held idle

**Why:** The gym env calls `reward_fn.compute()` in `step()` after the API call returns. The `info` dict is the raw JSON response forwarded from the backtest engine.

**How to apply:** When implementing a new reward that depends on trade activity, use `info.get("filled_orders", [])` to detect whether a trade was placed.
