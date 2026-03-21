"""Platform strategy definitions for each market regime.

One ``StrategyDefinition``-compatible dict is provided per ``RegimeType``.
Each dict is validated against the backend ``StrategyDefinition`` Pydantic model
(``src/strategies/models.py``) before being sent to ``POST /api/v1/strategies``.

Regime → strategy mapping:

* ``TRENDING``        — MACD crossover + ADX > 25 entry, 2 % trailing stop exit
* ``MEAN_REVERTING``  — RSI oversold (<30) + Bollinger lower-band entry, RSI
                        overbought (>70) exit
* ``HIGH_VOLATILITY`` — Tight 1 % stop-loss, small 3 % position, ATR exit via
                        max-hold candles
* ``LOW_VOLATILITY``  — Bollinger squeeze breakout entry, MACD momentum exit,
                        larger 10 % position
"""

from __future__ import annotations

from typing import Any, Protocol

import structlog

from agent.strategies.regime.labeler import RegimeType

logger = structlog.get_logger(__name__)


class _StrategyCreator(Protocol):
    """Structural type for any object that can create a platform strategy.

    Matches ``PlatformRESTClient.create_strategy`` so callers can pass the
    real client in production or a mock in tests without importing the
    concrete class here.
    """

    async def create_strategy(
        self,
        name: str,
        description: str,
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a strategy and return the platform response dict."""
        ...

# ---------------------------------------------------------------------------
# Pairs and timeframe shared across all regime strategies.
# ---------------------------------------------------------------------------

_PAIRS: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
_TIMEFRAME: str = "1h"

# ---------------------------------------------------------------------------
# Strategy definitions (raw dicts — serialised directly to the API body).
# Each dict is structurally equivalent to a ``StrategyDefinition`` model
# serialisation and passes platform-side Pydantic validation.
# ---------------------------------------------------------------------------

TRENDING_STRATEGY: dict[str, Any] = {
    "pairs": _PAIRS,
    "timeframe": _TIMEFRAME,
    "entry_conditions": {
        # MACD line must cross above the signal line — momentum confirmation.
        "macd_cross_above": True,
        # ADX > 25 confirms that a genuine trend is in place, not noise.
        "adx_above": 25.0,
    },
    "exit_conditions": {
        # Trailing stop 2 % from the equity peak — rides the trend while
        # protecting gains.  The backend executor applies this as a percentage
        # trailing stop from the position's highest unrealised equity.
        "trailing_stop_pct": 2.0,
        # Hard take-profit at 8 % in case the trailing stop is not triggered.
        "take_profit_pct": 8.0,
        # Safety stop-loss at 3 % for catastrophic moves against the trend.
        "stop_loss_pct": 3.0,
        # Exit after 72 candles (3 days on 1h timeframe) if none of the above
        # trigger, preventing indefinite position holding.
        "max_hold_candles": 72,
    },
    "position_size_pct": 7,
    "max_positions": 3,
    "model_type": "rule_based",
}

MEAN_REVERTING_STRATEGY: dict[str, Any] = {
    "pairs": _PAIRS,
    "timeframe": _TIMEFRAME,
    "entry_conditions": {
        # RSI < 30 signals the asset is oversold — price likely to mean-revert.
        "rsi_below": 30.0,
        # Price at or below the lower Bollinger Band confirms the extreme
        # deviation from the rolling mean.
        "bb_below_lower": True,
    },
    "exit_conditions": {
        # RSI > 70 indicates the asset is now overbought — mean reversion
        # is complete and the position should be closed for profit.
        "rsi_above": 70.0,
        # Hard take-profit at 5 % captures the typical mean-reversion move
        # without waiting for RSI to reach overbought territory.
        "take_profit_pct": 5.0,
        # Stop-loss at 2 % — mean-reversion entries can be wrong; cut losses
        # quickly if price continues lower.
        "stop_loss_pct": 2.0,
        # Exit after 48 candles (2 days) if mean-reversion has not played out;
        # avoids converting a short-term trade into a long-term holding.
        "max_hold_candles": 48,
    },
    "position_size_pct": 8,
    "max_positions": 3,
    "model_type": "rule_based",
}

HIGH_VOLATILITY_STRATEGY: dict[str, Any] = {
    "pairs": _PAIRS,
    "timeframe": _TIMEFRAME,
    "entry_conditions": {
        # MACD cross above for a directional signal even during high volatility.
        "macd_cross_above": True,
        # Require elevated volume (1.5× the 20-period volume MA) to filter
        # noise and ensure the move has backing participation.
        "volume_above_ma": 1.5,
    },
    "exit_conditions": {
        # Tight 1 % stop-loss — high volatility means large swings; capital
        # preservation is the primary objective.
        "stop_loss_pct": 1.0,
        # Conservative 3 % take-profit — lock in gains quickly before
        # volatility erases them.
        "take_profit_pct": 3.0,
        # Exit after 24 candles (1 day on 1h timeframe); high-volatility
        # trades should be short-duration.
        "max_hold_candles": 24,
    },
    # Small position size (3 %) to limit exposure per trade during
    # high-volatility regimes.
    "position_size_pct": 3,
    "max_positions": 2,
    "model_type": "rule_based",
}

LOW_VOLATILITY_STRATEGY: dict[str, Any] = {
    "pairs": _PAIRS,
    "timeframe": _TIMEFRAME,
    "entry_conditions": {
        # Bollinger squeeze breakout: price breaks above the upper Bollinger
        # Band after a period of compression (low volatility squeezes the
        # bands), signalling the start of a new directional move.
        "bb_above_upper": True,
        # MACD cross above confirms that the breakout has momentum, not just
        # a brief wick above the band.
        "macd_cross_above": True,
    },
    "exit_conditions": {
        # MACD cross below signals that momentum has faded and the squeeze
        # breakout move is over.
        "macd_cross_below": True,
        # Take-profit at 6 % — breakouts from low-volatility squeezes can
        # be sizeable; capture a meaningful portion.
        "take_profit_pct": 6.0,
        # Stop-loss at 2 % — a tight stop relative to the expected move;
        # breakout failures can reverse sharply.
        "stop_loss_pct": 2.0,
        # Exit after 96 candles (4 days) if momentum does not materialise;
        # low-volatility breakouts can sometimes take time to develop.
        "max_hold_candles": 96,
    },
    # Larger position size (10 %) appropriate for low-volatility regimes
    # where risk of catastrophic loss is reduced.
    "position_size_pct": 10,
    "max_positions": 3,
    "model_type": "rule_based",
}

# ---------------------------------------------------------------------------
# Name and description metadata per regime.
# ---------------------------------------------------------------------------

_REGIME_METADATA: dict[RegimeType, tuple[str, str]] = {
    RegimeType.TRENDING: (
        "Regime-Trending: MACD + ADX Momentum",
        (
            "Designed for trending market regimes (ADX > 25). "
            "Enters on MACD crossover above signal line with ADX trend confirmation. "
            "Uses a 2 % trailing stop to ride the trend and protect gains, "
            "with a hard take-profit at 8 % and stop-loss at 3 %. "
            "Pairs: BTCUSDT, ETHUSDT, SOLUSDT. Timeframe: 1h."
        ),
    ),
    RegimeType.MEAN_REVERTING: (
        "Regime-MeanReverting: RSI + Bollinger Band Bounce",
        (
            "Designed for mean-reverting market regimes. "
            "Enters when RSI drops below 30 and price touches the lower Bollinger Band. "
            "Exits when RSI rises above 70 (overbought) or at 5 % take-profit. "
            "Stop-loss at 2 %. Maximum hold 48 candles (2 days on 1h). "
            "Pairs: BTCUSDT, ETHUSDT, SOLUSDT. Timeframe: 1h."
        ),
    ),
    RegimeType.HIGH_VOLATILITY: (
        "Regime-HighVolatility: Tight Stop Capital Preservation",
        (
            "Designed for high-volatility market regimes. "
            "Enters on MACD crossover with elevated volume (1.5× MA). "
            "Uses a tight 1 % stop-loss and small 3 % position size "
            "to limit exposure. Take-profit at 3 %, maximum hold 24 candles. "
            "Pairs: BTCUSDT, ETHUSDT, SOLUSDT. Timeframe: 1h."
        ),
    ),
    RegimeType.LOW_VOLATILITY: (
        "Regime-LowVolatility: Bollinger Squeeze Breakout",
        (
            "Designed for low-volatility market regimes. "
            "Enters on a Bollinger Band squeeze breakout (price above upper band) "
            "confirmed by MACD crossover. Exits on MACD cross below signal or "
            "at 6 % take-profit. Larger 10 % position size appropriate for "
            "reduced volatility risk. "
            "Pairs: BTCUSDT, ETHUSDT, SOLUSDT. Timeframe: 1h."
        ),
    ),
}

# ---------------------------------------------------------------------------
# Regime → definition lookup (for programmatic access without branching).
# ---------------------------------------------------------------------------

STRATEGY_BY_REGIME: dict[RegimeType, dict[str, Any]] = {
    RegimeType.TRENDING: TRENDING_STRATEGY,
    RegimeType.MEAN_REVERTING: MEAN_REVERTING_STRATEGY,
    RegimeType.HIGH_VOLATILITY: HIGH_VOLATILITY_STRATEGY,
    RegimeType.LOW_VOLATILITY: LOW_VOLATILITY_STRATEGY,
}


# ---------------------------------------------------------------------------
# Public factory: create all 4 strategies via REST API.
# ---------------------------------------------------------------------------


async def create_regime_strategies(
    rest_client: _StrategyCreator,
    agent_id: str,
) -> dict[RegimeType, str]:
    """Create all four regime strategies on the platform via REST API.

    Sends ``POST /api/v1/strategies`` for each regime strategy definition.
    Strategies are idempotent from the perspective of this function — each
    call creates new strategy records regardless of prior runs (the platform
    does not enforce name uniqueness).

    The returned dict maps each ``RegimeType`` to the ``strategy_id`` UUID
    string returned by the platform.  This dict is intended to be passed
    directly to the regime switcher so it can dispatch live trades to the
    correct strategy based on the current classified regime.

    Args:
        rest_client: An instance of ``PlatformRESTClient`` (or any object
            with a ``create_strategy(name, description, definition)`` async
            method that returns a dict containing a ``"strategy_id"`` key).
            The caller is responsible for the client's lifecycle.
        agent_id: UUID string of the agent that will own the strategies.
            Not sent to the API directly — used for structured logging so
            callers can correlate which agent's strategies were created.

    Returns:
        A dict mapping ``RegimeType`` → ``strategy_id`` (platform UUID
        string) for the four created strategies.

    Raises:
        RuntimeError: If any strategy creation request fails or the response
            does not contain a ``"strategy_id"`` field.  The error message
            includes the regime name and the error detail for diagnostics.
    """
    strategy_ids: dict[RegimeType, str] = {}

    for regime, definition in STRATEGY_BY_REGIME.items():
        name, description = _REGIME_METADATA[regime]

        logger.info(
            "agent.strategy.regime.strategy.creating",
            regime=regime.value,
            name=name,
            agent_id=agent_id,
        )

        try:
            response = await rest_client.create_strategy(
                name=name,
                description=description,
                definition=definition,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to create strategy for regime '{regime.value}': {exc}"
            ) from exc

        if "error" in response:
            raise RuntimeError(
                f"Platform rejected strategy creation for regime "
                f"'{regime.value}': {response['error']}"
            )

        strategy_id: str | None = response.get("strategy_id")
        if not strategy_id:
            raise RuntimeError(
                f"Platform response for regime '{regime.value}' did not "
                f"contain a 'strategy_id'. Response: {response}"
            )

        strategy_ids[regime] = strategy_id
        logger.info(
            "agent.strategy.regime.strategy.created",
            regime=regime.value,
            strategy_id=strategy_id,
            agent_id=agent_id,
        )

    logger.info(
        "agent.strategy.regime.strategy.all_created",
        agent_id=agent_id,
        count=len(strategy_ids),
        strategy_ids={r.value: sid for r, sid in strategy_ids.items()},
    )
    return strategy_ids


__all__ = [
    "TRENDING_STRATEGY",
    "MEAN_REVERTING_STRATEGY",
    "HIGH_VOLATILITY_STRATEGY",
    "LOW_VOLATILITY_STRATEGY",
    "STRATEGY_BY_REGIME",
    "create_regime_strategies",
]
