"""Multi-asset portfolio allocation environment."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import numpy as np
from gymnasium import spaces

from tradeready_gym.envs.base_trading_env import BaseTradingEnv
from tradeready_gym.rewards.custom_reward import CustomReward


class MultiAssetTradingEnv(BaseTradingEnv):
    """Trade multiple crypto pairs using portfolio-weight actions.

    Action space: ``Box(0, 1, shape=(N,))`` where N is the number of pairs.
    Each action element is the target portfolio weight for that pair.
    The environment generates rebalancing orders to reach the target allocation.

    Args:
        symbols:  List of trading pairs (e.g. ``["BTCUSDT", "ETHUSDT"]``).
        **kwargs: Passed to :class:`BaseTradingEnv`.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        api_key: str = "",
        base_url: str = "http://localhost:8000",
        reward_function: CustomReward | None = None,
        **kwargs: Any,
    ) -> None:
        self.symbols = [s.upper() for s in (symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT"])]
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            pairs=self.symbols,
            reward_function=reward_function,
            **kwargs,
        )
        n = len(self.symbols)
        self.action_space = spaces.Box(low=0.0, high=1.0, shape=(n,), dtype=np.float32)

    def _execute_action(self, action: Any) -> list[dict[str, Any]]:
        """Translate portfolio weight targets into rebalancing orders."""
        orders: list[dict[str, Any]] = []
        weights = np.clip(action, 0.0, 1.0)
        total = weights.sum()
        if total > 1.0:
            weights = weights / total  # normalize to sum <= 1

        portfolio = self._last_step_result.get("portfolio", {})
        equity = float(portfolio.get("total_equity", self.starting_balance))
        prices = self._last_step_result.get("prices", {})

        # Current holdings by symbol
        positions = portfolio.get("positions", [])
        current_values: dict[str, float] = {}
        current_qtys: dict[str, float] = {}
        for pos in positions:
            sym = pos.get("symbol", "")
            current_values[sym] = float(pos.get("market_value", 0))
            current_qtys[sym] = float(pos.get("quantity", 0))

        for i, symbol in enumerate(self.symbols):
            target_value = equity * float(weights[i])
            current_value = current_values.get(symbol, 0.0)
            price = float(prices.get(symbol, 0))
            if price <= 0:
                continue

            diff = target_value - current_value
            quantity = abs(Decimal(str(diff / price)))

            if quantity <= 0:
                continue

            if diff > equity * 0.01:  # buy threshold: 1% of equity
                orders.append({
                    "symbol": symbol,
                    "side": "buy",
                    "type": "market",
                    "quantity": str(quantity),
                })
            elif diff < -equity * 0.01:  # sell threshold
                # Cap sell quantity at current holding
                sell_qty = min(float(quantity), current_qtys.get(symbol, 0.0))
                if sell_qty > 0:
                    orders.append({
                        "symbol": symbol,
                        "side": "sell",
                        "type": "market",
                        "quantity": str(Decimal(str(sell_qty))),
                    })

        return orders
