"""Single-asset trading environment with discrete or continuous actions."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import numpy as np
from gymnasium import spaces

from tradeready_gym.envs.base_trading_env import BaseTradingEnv
from tradeready_gym.rewards.custom_reward import CustomReward


class SingleAssetTradingEnv(BaseTradingEnv):
    """Trade a single crypto pair using discrete or continuous actions.

    Discrete mode (default):
        ``Discrete(3)`` — 0=Hold, 1=Buy (position_size_pct), 2=Sell (close position).

    Continuous mode:
        ``Box(-1, 1, shape=(1,))`` — negative=sell, positive=buy, magnitude=position size.

    Args:
        symbol:            Trading pair symbol (e.g. ``"BTCUSDT"``).
        continuous:        Use continuous action space if ``True``.
        position_size_pct: Fraction of equity to use per trade (discrete mode).
        **kwargs:          Passed to :class:`BaseTradingEnv`.
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        continuous: bool = False,
        position_size_pct: float = 0.1,
        api_key: str = "",
        base_url: str = "http://localhost:8000",
        reward_function: CustomReward | None = None,
        **kwargs: Any,
    ) -> None:
        self.symbol = symbol.upper()
        self.continuous = continuous
        self.position_size_pct = position_size_pct
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            pairs=[self.symbol],
            reward_function=reward_function,
            **kwargs,
        )
        if continuous:
            self.action_space = spaces.Box(
                low=-1.0, high=1.0, shape=(1,), dtype=np.float32
            )
        else:
            self.action_space = spaces.Discrete(3)

    def _execute_action(self, action: Any) -> list[dict[str, Any]]:
        """Translate discrete/continuous action to API order(s)."""
        orders: list[dict[str, Any]] = []
        portfolio = self._last_step_result.get("portfolio", {})
        equity = float(portfolio.get("total_equity", self.starting_balance))
        current_price = float(
            self._last_step_result.get("prices", {}).get(self.symbol, 0)
        )

        if current_price <= 0:
            return orders

        if self.continuous:
            signal = float(np.clip(action[0], -1.0, 1.0))
            if abs(signal) < 0.05:  # dead zone → hold
                return orders
            size_pct = abs(signal) * self.position_size_pct
            quantity = Decimal(str(equity * size_pct / current_price))
            if quantity <= 0:
                return orders
            side = "buy" if signal > 0 else "sell"
            orders.append({
                "symbol": self.symbol,
                "side": side,
                "type": "market",
                "quantity": str(quantity),
            })
        else:
            action_int = int(action)
            if action_int == 0:  # hold
                return orders
            elif action_int == 1:  # buy
                quantity = Decimal(
                    str(equity * self.position_size_pct / current_price)
                )
                if quantity > 0:
                    orders.append({
                        "symbol": self.symbol,
                        "side": "buy",
                        "type": "market",
                        "quantity": str(quantity),
                    })
            elif action_int == 2:  # sell (close position)
                positions = portfolio.get("positions", [])
                for pos in positions:
                    if pos.get("symbol") == self.symbol:
                        qty = pos.get("quantity", "0")
                        if float(qty) > 0:
                            orders.append({
                                "symbol": self.symbol,
                                "side": "sell",
                                "type": "market",
                                "quantity": str(qty),
                            })
                        break

        return orders
