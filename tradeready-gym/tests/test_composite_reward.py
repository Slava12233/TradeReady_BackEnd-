"""Unit tests for CompositeReward.

Tests cover:
  - Construction validation (bad weights, bad window)
  - Per-component behaviour in isolation
  - Combined reward sign and magnitude
  - reset() clears all per-episode state
  - Integration: CompositeReward accepted by SingleAssetTradingEnv
  - RLConfig accepts 'composite' reward_type
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tradeready_gym.rewards.composite import CompositeReward


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _info(
    *,
    filled_orders: list[Any] | None = None,
    starting_balance: float = 10_000.0,
    total_equity: float = 10_000.0,
) -> dict[str, Any]:
    """Build a minimal step info dict matching the backtest API shape."""
    return {
        "filled_orders": filled_orders if filled_orders is not None else [],
        "portfolio": {
            "starting_balance": str(starting_balance),
            "total_equity": str(total_equity),
        },
    }


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestCompositeRewardConstruction:
    """Constructor validation."""

    def test_default_construction_succeeds(self) -> None:
        reward = CompositeReward()
        assert reward is not None

    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError, match="sum to 1.0"):
            CompositeReward(
                sortino_weight=0.4,
                pnl_weight=0.3,
                activity_weight=0.2,
                drawdown_weight=0.2,  # total = 1.1
            )

    def test_weights_summing_to_one_succeed(self) -> None:
        reward = CompositeReward(
            sortino_weight=0.5,
            pnl_weight=0.3,
            activity_weight=0.1,
            drawdown_weight=0.1,
        )
        assert reward is not None

    def test_sortino_window_below_two_raises(self) -> None:
        with pytest.raises(ValueError, match="sortino_window must be"):
            CompositeReward(sortino_window=1)

    def test_negative_activity_bonus_raises(self) -> None:
        with pytest.raises(ValueError, match="activity_bonus must be non-negative"):
            CompositeReward(activity_bonus=-0.5)

    def test_floating_point_weights_accepted(self) -> None:
        # Weights that are close to 1.0 within floating-point tolerance
        reward = CompositeReward(
            sortino_weight=0.4,
            pnl_weight=0.3,
            activity_weight=0.2,
            drawdown_weight=0.1,
        )
        assert reward is not None


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------

class TestCompositeRewardReset:
    """reset() must clear all per-episode state."""

    def test_reset_clears_sortino_history(self) -> None:
        reward = CompositeReward()
        # Accumulate several returns to build Sortino history
        for _ in range(10):
            reward.compute(10_000, 10_100, _info())
        assert len(reward._returns) > 0
        assert reward._prev_sortino != 0.0

        reward.reset()
        assert reward._returns == []
        assert reward._prev_sortino == 0.0

    def test_reset_clears_peak_equity(self) -> None:
        reward = CompositeReward()
        reward.compute(10_000, 12_000, _info())
        assert reward._peak_equity == 12_000.0

        reward.reset()
        assert reward._peak_equity == 0.0

    def test_reset_clears_idle_steps(self) -> None:
        reward = CompositeReward()
        # Five hold steps accumulate idle count
        for _ in range(5):
            reward.compute(10_000, 10_000, _info(filled_orders=[]))
        assert reward._idle_steps == 5

        reward.reset()
        assert reward._idle_steps == 0

    def test_reward_after_reset_matches_fresh_instance(self) -> None:
        fresh = CompositeReward()
        r_fresh = fresh.compute(10_000, 10_100, _info())

        used = CompositeReward()
        # Pollute state
        for _ in range(5):
            used.compute(10_000, 9_900, _info())
        used.reset()

        r_used = used.compute(10_000, 10_100, _info())
        # Both should produce the same value (first step after reset)
        assert math.isclose(r_fresh, r_used, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# PnL normalised component
# ---------------------------------------------------------------------------

class TestPnLNormalisedComponent:
    """_pnl_normalised scales by starting_balance, not curr_equity."""

    def test_positive_pnl_returns_positive(self) -> None:
        reward = CompositeReward(
            sortino_weight=0.0,
            pnl_weight=1.0,
            activity_weight=0.0,
            drawdown_weight=0.0,
        )
        r = reward.compute(10_000, 10_100, _info(starting_balance=10_000))
        # pnl_norm = 100 / 10_000 = 0.01
        assert math.isclose(r, 0.01, rel_tol=1e-6)

    def test_negative_pnl_returns_negative(self) -> None:
        reward = CompositeReward(
            sortino_weight=0.0,
            pnl_weight=1.0,
            activity_weight=0.0,
            drawdown_weight=0.0,
        )
        r = reward.compute(10_000, 9_900, _info(starting_balance=10_000))
        assert math.isclose(r, -0.01, rel_tol=1e-6)

    def test_fallback_to_constructor_starting_balance(self) -> None:
        # info dict has no portfolio key
        reward = CompositeReward(
            sortino_weight=0.0,
            pnl_weight=1.0,
            activity_weight=0.0,
            drawdown_weight=0.0,
            starting_balance=5_000.0,
        )
        r = reward.compute(5_000, 5_100, {})
        # pnl_norm = 100 / 5_000 = 0.02
        assert math.isclose(r, 0.02, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# Activity component
# ---------------------------------------------------------------------------

class TestActivityComponent:
    """Activity bonus and inactivity penalty."""

    def _activity_only(self) -> CompositeReward:
        """Reward with only the activity component active."""
        return CompositeReward(
            sortino_weight=0.0,
            pnl_weight=0.0,
            activity_weight=1.0,
            drawdown_weight=0.0,
            activity_bonus=1.0,
        )

    def test_trading_step_gives_positive_bonus(self) -> None:
        reward = self._activity_only()
        r = reward.compute(10_000, 10_000, _info(filled_orders=[{"order_id": "1"}]))
        assert math.isclose(r, 1.0, rel_tol=1e-9)

    def test_idle_step_gives_small_negative(self) -> None:
        reward = self._activity_only()
        r = reward.compute(10_000, 10_000, _info(filled_orders=[]))
        # First idle step: penalty_factor = 1/50 = 0.02
        assert r < 0.0
        assert r > -1.0  # capped

    def test_idle_steps_grow_penalty(self) -> None:
        reward = self._activity_only()
        first = reward.compute(10_000, 10_000, _info())
        second = reward.compute(10_000, 10_000, _info())
        assert second < first  # penalty grows with consecutive idle steps

    def test_idle_penalty_caps_at_activity_bonus(self) -> None:
        reward = self._activity_only()
        # Force many idle steps past the sortino_window (default 50)
        for _ in range(100):
            reward.compute(10_000, 10_000, _info())
        r = reward.compute(10_000, 10_000, _info())
        # Should be capped at -activity_bonus = -1.0
        assert math.isclose(r, -1.0, rel_tol=1e-9)

    def test_trade_resets_idle_counter(self) -> None:
        reward = self._activity_only()
        # Accumulate some idle steps
        for _ in range(20):
            reward.compute(10_000, 10_000, _info())
        assert reward._idle_steps == 20

        # A trade resets the counter
        reward.compute(10_000, 10_000, _info(filled_orders=[{"order_id": "x"}]))
        assert reward._idle_steps == 0

    def test_trade_after_long_idle_gives_bonus_not_penalty(self) -> None:
        reward = self._activity_only()
        for _ in range(60):
            reward.compute(10_000, 10_000, _info())
        r = reward.compute(10_000, 10_000, _info(filled_orders=[{"order_id": "y"}]))
        assert r > 0.0  # positive bonus even after long idle stretch


# ---------------------------------------------------------------------------
# Drawdown penalty component
# ---------------------------------------------------------------------------

class TestDrawdownPenaltyComponent:
    """Drawdown penalty is negative when below peak."""

    def _drawdown_only(self) -> CompositeReward:
        return CompositeReward(
            sortino_weight=0.0,
            pnl_weight=0.0,
            activity_weight=0.0,
            drawdown_weight=1.0,
        )

    def test_at_peak_no_penalty(self) -> None:
        reward = self._drawdown_only()
        # Equity rises: always at peak
        r = reward.compute(10_000, 10_100, _info())
        assert math.isclose(r, 0.0, abs_tol=1e-9)

    def test_below_peak_gives_negative_reward(self) -> None:
        reward = self._drawdown_only()
        reward.compute(10_000, 10_100, _info())  # set peak to 10_100
        r = reward.compute(10_100, 9_900, _info())  # fall to 9_900
        assert r < 0.0

    def test_drawdown_magnitude(self) -> None:
        reward = self._drawdown_only()
        reward.compute(10_000, 10_000, _info())  # peak = 10_000
        r = reward.compute(10_000, 9_000, _info())  # drawdown = 10%
        # penalty = -drawdown = -(10_000 - 9_000) / 10_000 = -0.1
        assert math.isclose(r, -0.1, rel_tol=1e-6)

    def test_new_peak_resets_drawdown(self) -> None:
        reward = self._drawdown_only()
        reward.compute(10_000, 10_000, _info())   # peak = 10_000
        reward.compute(10_000, 9_000, _info())    # below peak
        r = reward.compute(9_000, 11_000, _info())  # new peak
        assert math.isclose(r, 0.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Sortino increment component
# ---------------------------------------------------------------------------

class TestSortinoIncrementComponent:
    """Sortino increment accumulates over the window."""

    def _sortino_only(self, window: int = 10) -> CompositeReward:
        return CompositeReward(
            sortino_weight=1.0,
            pnl_weight=0.0,
            activity_weight=0.0,
            drawdown_weight=0.0,
            sortino_window=window,
        )

    def test_first_step_returns_zero(self) -> None:
        reward = self._sortino_only()
        r = reward.compute(10_000, 10_100, _info())
        assert r == 0.0  # only 1 sample, not enough for variance

    def test_second_step_may_be_nonzero(self) -> None:
        reward = self._sortino_only()
        reward.compute(10_000, 10_100, _info())
        r = reward.compute(10_100, 10_200, _info())
        assert isinstance(r, float)

    def test_pure_uptrend_no_downside_penalty(self) -> None:
        reward = self._sortino_only()
        cumulative = 0.0
        equity = 10_000.0
        for _ in range(15):
            next_equity = equity * 1.01  # +1% each step
            cumulative += reward.compute(equity, next_equity, _info())
            equity = next_equity
        # In a pure uptrend Sortino should trend positive
        assert cumulative > 0.0

    def test_window_rolls_oldest_returns(self) -> None:
        reward = self._sortino_only(window=5)
        equity = 10_000.0
        for _ in range(10):  # more steps than window
            next_equity = equity * 1.005
            reward.compute(equity, next_equity, _info())
            equity = next_equity
        assert len(reward._returns) <= 5


# ---------------------------------------------------------------------------
# Combined reward
# ---------------------------------------------------------------------------

class TestCombinedReward:
    """Tests on the full composite reward (default weights)."""

    def test_compute_returns_float(self) -> None:
        reward = CompositeReward()
        r = reward.compute(10_000, 10_100, _info())
        assert isinstance(r, float)

    def test_profitable_trading_step_is_positive(self) -> None:
        reward = CompositeReward()
        # Warm up Sortino window
        equity = 10_000.0
        for _ in range(5):
            next_equity = equity * 1.002
            reward.compute(equity, next_equity, _info(filled_orders=[{"id": "x"}]))
            equity = next_equity
        r = reward.compute(equity, equity * 1.01, _info(filled_orders=[{"id": "y"}]))
        # Positive PnL + active trade + Sortino improvement should outweigh small drawdown
        assert r > 0.0

    def test_loss_with_inactivity_is_negative(self) -> None:
        reward = CompositeReward()
        # Establish a peak
        reward.compute(10_000, 11_000, _info(filled_orders=[{"id": "z"}]))
        # Then take a loss while being idle
        r = reward.compute(11_000, 10_000, _info(filled_orders=[]))
        assert r < 0.0

    def test_weights_sum_preserved_in_output(self) -> None:
        """Verify that halving one component and doubling another changes the output."""
        default = CompositeReward()
        custom = CompositeReward(
            sortino_weight=0.8,
            pnl_weight=0.1,
            activity_weight=0.05,
            drawdown_weight=0.05,
        )
        info = _info(filled_orders=[{"id": "t"}], starting_balance=10_000)
        r_default = default.compute(10_000, 10_100, info)
        r_custom = custom.compute(10_000, 10_100, info)
        # Values should differ because weights differ
        assert not math.isclose(r_default, r_custom, rel_tol=1e-3)

    def test_inactivity_penalty_prevents_always_hold(self) -> None:
        """Holding cash for many steps should produce net-negative reward."""
        reward = CompositeReward()
        # Flat equity, zero trades for 60 steps
        total = 0.0
        for _ in range(60):
            total += reward.compute(10_000, 10_000, _info(filled_orders=[]))
        assert total < 0.0, "Always-hold should have negative cumulative reward"

    def test_no_nan_in_output(self) -> None:
        """Reward must never be NaN regardless of extreme equity moves."""
        reward = CompositeReward()
        extreme_cases = [
            (0.0, 0.0),          # zero equity
            (10_000, 0.001),     # near-zero loss
            (0.001, 10_000),     # recovery from near-zero
            (10_000, 1_000_000), # extreme gain
        ]
        for prev, curr in extreme_cases:
            r = reward.compute(prev, curr, _info(starting_balance=10_000))
            assert not math.isnan(r), f"NaN for prev={prev}, curr={curr}"
            assert not math.isinf(r), f"Inf for prev={prev}, curr={curr}"


# ---------------------------------------------------------------------------
# Integration: CompositeReward works with the gym env
# ---------------------------------------------------------------------------

class TestCompositeRewardGymIntegration:
    """Verify CompositeReward is accepted by SingleAssetTradingEnv."""

    def test_env_accepts_composite_reward(self) -> None:
        from tradeready_gym.envs.single_asset_env import SingleAssetTradingEnv

        def _mock_api_call(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            if "create" in path:
                return {"session_id": "test-session"}
            if "start" in path:
                return {"status": "active"}
            if "step" in path:
                return {
                    "virtual_time": "2025-01-01T00:01:00Z",
                    "step": 1,
                    "total_steps": 100,
                    "progress_pct": 1.0,
                    "prices": {"BTCUSDT": "97000.00"},
                    "filled_orders": [{"order_id": "o1"}],
                    "portfolio": {
                        "total_equity": "10100.00",
                        "available_cash": "10100.00",
                        "locked_cash": "0",
                        "total_position_value": "0",
                        "unrealized_pnl": "0",
                        "realized_pnl": "100.00",
                        "total_pnl": "100.00",
                        "roi_pct": "1.0",
                        "starting_balance": "10000.00",
                        "positions": [],
                    },
                    "is_complete": False,
                }
            if "candles" in path:
                return {
                    "candles": [
                        {
                            "time": f"2025-01-01T00:{i:02d}:00Z",
                            "open": str(97000 + i * 10),
                            "high": str(97050 + i * 10),
                            "low": str(96950 + i * 10),
                            "close": str(97020 + i * 10),
                            "volume": "100.5",
                            "trade_count": 50,
                        }
                        for i in range(30)
                    ]
                }
            return {}

        with (
            patch("tradeready_gym.envs.base_trading_env.httpx.Client") as mock_cls,
            patch("tradeready_gym.envs.base_trading_env.TrainingTracker"),
        ):
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            def _request(method: str, path: str, **kwargs: Any) -> MagicMock:
                resp = MagicMock()
                resp.status_code = 200
                resp.content = b"ok"
                resp.json.return_value = _mock_api_call(method, path, **kwargs)
                resp.raise_for_status.return_value = None
                return resp

            mock_client.request.side_effect = _request

            reward_fn = CompositeReward()
            env = SingleAssetTradingEnv(
                symbol="BTCUSDT",
                api_key="test-key",
                reward_function=reward_fn,
            )
            env.reset()
            _, reward, _, _, _ = env.step(1)  # buy action
            assert isinstance(reward, float)
            assert not math.isnan(reward)
            env.close()


# ---------------------------------------------------------------------------
# RLConfig accepts 'composite' reward_type
# ---------------------------------------------------------------------------

class TestRLConfigComposite:
    """Verify RLConfig validator accepts 'composite' and rejects unknown types."""

    def test_composite_is_valid_reward_type(self) -> None:
        from agent.strategies.rl.config import RLConfig

        cfg = RLConfig(reward_type="composite")
        assert cfg.reward_type == "composite"

    def test_unknown_reward_type_still_rejected(self) -> None:
        from pydantic import ValidationError

        from agent.strategies.rl.config import RLConfig

        with pytest.raises(ValidationError):
            RLConfig(reward_type="invalid_type")

    def test_composite_weight_fields_have_defaults(self) -> None:
        from agent.strategies.rl.config import RLConfig

        cfg = RLConfig(reward_type="composite")
        assert math.isclose(
            cfg.composite_sortino_weight
            + cfg.composite_pnl_weight
            + cfg.composite_activity_weight
            + cfg.composite_drawdown_weight,
            1.0,
            abs_tol=1e-9,
        )

    def test_build_reward_returns_composite_instance(self) -> None:
        from agent.strategies.rl.config import RLConfig
        from agent.strategies.rl.train import _build_reward

        cfg = RLConfig(reward_type="composite")
        reward = _build_reward(cfg)
        assert isinstance(reward, CompositeReward)

    def test_build_reward_passes_window_from_config(self) -> None:
        from agent.strategies.rl.config import RLConfig
        from agent.strategies.rl.train import _build_reward

        cfg = RLConfig(reward_type="composite", sharpe_window=30)
        reward = _build_reward(cfg)
        assert isinstance(reward, CompositeReward)
        assert reward._sortino_window == 30

    def test_build_reward_passes_custom_weights(self) -> None:
        from agent.strategies.rl.config import RLConfig
        from agent.strategies.rl.train import _build_reward

        cfg = RLConfig(
            reward_type="composite",
            composite_sortino_weight=0.5,
            composite_pnl_weight=0.3,
            composite_activity_weight=0.1,
            composite_drawdown_weight=0.1,
        )
        reward = _build_reward(cfg)
        assert isinstance(reward, CompositeReward)
        assert math.isclose(reward._sortino_weight, 0.5, rel_tol=1e-9)
        assert math.isclose(reward._pnl_weight, 0.3, rel_tol=1e-9)

    def test_all_reward_types_still_build(self) -> None:
        from agent.strategies.rl.config import RLConfig
        from agent.strategies.rl.train import _build_reward

        for rtype in ("pnl", "sharpe", "sortino", "drawdown", "composite"):
            cfg = RLConfig(reward_type=rtype)
            reward = _build_reward(cfg)
            assert reward is not None
