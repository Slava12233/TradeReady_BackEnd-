"""Composite reward function targeting aggressive 10% monthly returns.

Combines four objectives with configurable weights::

    reward = (
        sortino_weight    * sortino_increment
        + pnl_weight      * pnl_normalized
        + activity_weight * activity_bonus
        + drawdown_weight * drawdown_penalty
    )

Design rationale:
    - Sortino over Sharpe: only downside volatility is penalised, letting
      large upside moves accrue freely.
    - Normalised PnL: raw equity delta is scaled by starting_balance so the
      reward magnitude is stable across episodes with different equity curves.
    - Activity bonus: a positive signal every time the agent places at least
      one trade, and a symmetric *inactivity penalty* when it holds
      completely idle.  This discourages the degenerate "always hold cash"
      policy that maximises Sortino by never acting.
    - Drawdown penalty: a signed negative component proportional to the
      current drawdown from the running peak, decoupled from PnL so
      underwater episodes receive an ongoing penalty regardless of the
      current step's direction.
"""

from __future__ import annotations

import math
from typing import Any

from tradeready_gym.rewards.custom_reward import CustomReward

# Default component weights as documented in the task specification.
# They sum to 1.0 so the composite reward has the same order of magnitude
# as each individual component.
_DEFAULT_SORTINO_WEIGHT: float = 0.4
_DEFAULT_PNL_WEIGHT: float = 0.3
_DEFAULT_ACTIVITY_WEIGHT: float = 0.2
_DEFAULT_DRAWDOWN_WEIGHT: float = 0.1


class CompositeReward(CustomReward):
    """Multi-objective reward function for aggressive monthly-return targets.

    The reward is a weighted sum of four components:

    1. **Sortino increment** (weight=0.4) — Change in the rolling Sortino
       ratio from the previous step.  Uses only downside semi-deviation in
       the denominator, so large positive returns do not inflate the penalty.

    2. **PnL normalised** (weight=0.3) — Per-step equity delta divided by
       the starting balance, giving a scale-invariant return signal.

    3. **Activity bonus** (weight=0.2) — Positive constant when the agent
       trades, zero or negative when it holds idle.  Magnitude decays as the
       number of consecutive idle steps grows, capping at ``-activity_bonus``
       to avoid drowning the other components.

    4. **Drawdown penalty** (weight=0.1) — Negative value proportional to
       the current drawdown from the running equity peak.  Applied every step
       regardless of the current step direction.

    Args:
        sortino_weight: Weight for the Sortino increment component.
            Default 0.4.  Reduces downside-only risk.
        pnl_weight: Weight for the normalised PnL component.
            Default 0.3.  Directly rewards profitable trades.
        activity_weight: Weight for the activity bonus/penalty component.
            Default 0.2.  Discourages the degenerate hold-cash policy.
        drawdown_weight: Weight for the drawdown penalty component.
            Default 0.1.  Continuous penalty for being underwater.
        sortino_window: Rolling window length (steps) for Sortino calculation.
            Default 50 — same as ``SortinoReward`` default so hyperparameters
            are comparable across reward types.
        activity_bonus: Magnitude of the per-step activity bonus when a trade
            is placed.  The inactivity penalty is the mirror negative value
            scaled by the consecutive idle step count (capped at 1.0×).
            Default 1.0 — tuned so that ~5 idle steps produce the same
            magnitude as the activity bonus.
        starting_balance: Denominator for PnL normalisation.  The env passes
            ``info["portfolio"]["starting_balance"]`` each step; this value is
            used only as a fallback if the key is missing.  Default 10 000.
    """

    def __init__(
        self,
        *,
        sortino_weight: float = _DEFAULT_SORTINO_WEIGHT,
        pnl_weight: float = _DEFAULT_PNL_WEIGHT,
        activity_weight: float = _DEFAULT_ACTIVITY_WEIGHT,
        drawdown_weight: float = _DEFAULT_DRAWDOWN_WEIGHT,
        sortino_window: int = 50,
        activity_bonus: float = 1.0,
        starting_balance: float = 10_000.0,
    ) -> None:
        # Validate weights up-front so misconfiguration is caught at
        # construction time rather than silently producing NaN rewards.
        total = sortino_weight + pnl_weight + activity_weight + drawdown_weight
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(
                f"Component weights must sum to 1.0, got {total:.6f}. "
                f"Received sortino={sortino_weight}, pnl={pnl_weight}, "
                f"activity={activity_weight}, drawdown={drawdown_weight}."
            )
        if sortino_window < 2:
            raise ValueError(
                f"sortino_window must be >= 2 for variance to be defined, got {sortino_window}."
            )
        if activity_bonus < 0:
            raise ValueError(f"activity_bonus must be non-negative, got {activity_bonus}.")

        self._sortino_weight = sortino_weight
        self._pnl_weight = pnl_weight
        self._activity_weight = activity_weight
        self._drawdown_weight = drawdown_weight
        self._sortino_window = sortino_window
        self._activity_bonus = activity_bonus
        self._starting_balance = starting_balance

        # Mutable per-episode state — reset between episodes
        self._returns: list[float] = []
        self._prev_sortino: float = 0.0
        self._peak_equity: float = 0.0
        self._idle_steps: int = 0  # consecutive steps with zero trades

    # ------------------------------------------------------------------
    # CustomReward interface
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all per-episode state.  Called by the env at each episode start."""
        self._returns = []
        self._prev_sortino = 0.0
        self._peak_equity = 0.0
        self._idle_steps = 0

    def compute(
        self,
        prev_equity: float,
        curr_equity: float,
        info: dict[str, Any],
    ) -> float:
        """Compute the composite reward for a single environment step.

        Args:
            prev_equity: Portfolio equity at the end of the previous step.
            curr_equity: Portfolio equity at the end of the current step.
            info:        Full step result dict from the backtest API.  Expected
                         keys: ``"portfolio"`` (nested dict with
                         ``"starting_balance"``), ``"filled_orders"`` (list).

        Returns:
            Scalar reward: weighted combination of Sortino increment,
            normalised PnL, activity bonus/penalty, and drawdown penalty.
        """
        sortino_inc = self._sortino_increment(prev_equity, curr_equity)
        pnl_norm = self._pnl_normalised(prev_equity, curr_equity, info)
        activity = self._activity_component(info)
        drawdown = self._drawdown_penalty(curr_equity)

        return (
            self._sortino_weight * sortino_inc
            + self._pnl_weight * pnl_norm
            + self._activity_weight * activity
            + self._drawdown_weight * drawdown
        )

    # ------------------------------------------------------------------
    # Component helpers — each returns a signed scalar
    # ------------------------------------------------------------------

    def _sortino_increment(self, prev_equity: float, curr_equity: float) -> float:
        """Delta of the rolling Sortino ratio (penalises only downside vol).

        Returns 0.0 until the window has at least 2 samples so the first
        few steps do not produce degenerate rewards.
        """
        ret = (curr_equity - prev_equity) / prev_equity if prev_equity > 0.0 else 0.0
        self._returns.append(ret)
        if len(self._returns) > self._sortino_window:
            self._returns = self._returns[-self._sortino_window :]

        if len(self._returns) < 2:
            return 0.0

        mean = sum(self._returns) / len(self._returns)
        downside_sq = [min(r, 0.0) ** 2 for r in self._returns]
        downside_var = sum(downside_sq) / len(downside_sq)
        # Use a small epsilon instead of zero to avoid divide-by-zero when
        # all returns are non-negative (pure uptrend — the ideal scenario).
        downside_std = math.sqrt(downside_var) if downside_var > 0.0 else 1e-8

        sortino = mean / downside_std
        increment = sortino - self._prev_sortino
        self._prev_sortino = sortino
        return increment

    def _pnl_normalised(
        self,
        prev_equity: float,
        curr_equity: float,
        info: dict[str, Any],
    ) -> float:
        """Per-step PnL scaled by starting_balance.

        Scaling by ``starting_balance`` (not ``prev_equity``) keeps the
        reward magnitude consistent over long episodes where equity may drift
        far from the starting point.  A 1% gain always contributes
        0.01 * pnl_weight regardless of episode length.
        """
        portfolio = info.get("portfolio", {})
        # Prefer the authoritative value from the API; fall back to the
        # constructor default if the key is absent (e.g. in unit tests).
        starting = float(portfolio.get("starting_balance", self._starting_balance))
        denominator = starting if starting > 0.0 else 1.0
        return (curr_equity - prev_equity) / denominator

    def _activity_component(self, info: dict[str, Any]) -> float:
        """Activity bonus for trading; inactivity penalty for holding idle.

        The bonus is flat: ``+activity_bonus`` whenever filled_orders is
        non-empty.

        The penalty grows with consecutive idle steps to discourage prolonged
        inactivity: ``-activity_bonus * min(idle_steps / window, 1.0)``.
        This caps at ``-activity_bonus`` so the penalty never overwhelms the
        Sortino component in long flat markets.
        """
        filled_orders = info.get("filled_orders", [])
        traded = len(filled_orders) > 0

        if traded:
            self._idle_steps = 0
            return self._activity_bonus
        else:
            self._idle_steps += 1
            # Scale penalty linearly up to the window size, then cap at 1×.
            penalty_factor = min(self._idle_steps / max(self._sortino_window, 1), 1.0)
            return -self._activity_bonus * penalty_factor

    def _drawdown_penalty(self, curr_equity: float) -> float:
        """Negative reward proportional to current drawdown from equity peak.

        Returns 0.0 when the portfolio is at or above its all-time high.
        The penalty is expressed as a fraction of the peak (0.0–1.0) and is
        negated so it always subtracts from the composite reward.
        """
        if curr_equity > self._peak_equity:
            self._peak_equity = curr_equity

        if self._peak_equity <= 0.0:
            return 0.0

        drawdown = (self._peak_equity - curr_equity) / self._peak_equity
        return -drawdown  # negative: penalise being below peak
