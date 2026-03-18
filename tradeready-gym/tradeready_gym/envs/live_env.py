"""Live trading environment using real-time price feeds."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import numpy as np

from tradeready_gym.envs.base_trading_env import BaseTradingEnv

logger = logging.getLogger(__name__)
from tradeready_gym.rewards.custom_reward import CustomReward


class LiveTradingEnv(BaseTradingEnv):
    """Live trading environment using real-time market data.

    Unlike the backtest-backed environments, this environment uses the
    live market API endpoints. Each ``step()`` waits for the next candle
    interval before returning, making it suitable for real-time paper
    trading with RL agents.

    Args:
        symbol:            Trading pair symbol.
        step_interval_sec: Seconds to wait between steps (default 60 for 1m candles).
        **kwargs:          Passed to :class:`BaseTradingEnv`.
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        step_interval_sec: float = 60.0,
        api_key: str = "",
        base_url: str = "http://localhost:8000",
        reward_function: CustomReward | None = None,
        **kwargs: Any,
    ) -> None:
        self.symbol = symbol.upper()
        self.step_interval_sec = step_interval_sec
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            pairs=[self.symbol],
            reward_function=reward_function,
            **kwargs,
        )
        self._live_mode = True
        self._last_step_time: float = 0.0

    def _get_observation(self) -> np.ndarray:
        """Fetch live candle + portfolio data."""
        candle_data: dict[str, list[dict[str, Any]]] = {}
        resp = self._api_call(
            "GET",
            f"/api/v1/market/candles/{self.symbol}",
            params={"interval": self.timeframe, "limit": self.lookback_window},
        )
        candle_data[self.symbol] = resp.get("candles", [])

        portfolio_resp = self._api_call("GET", "/api/v1/account/portfolio")
        return self._obs_builder.build(candle_data, portfolio_resp)

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Reset the live environment (does not create a backtest session)."""
        # Skip the base class backtest session creation
        self._session_id = "live"
        self._step_count = 0
        self._episode_count += 1

        # Fetch initial portfolio
        portfolio = self._api_call("GET", "/api/v1/account/portfolio")
        self._prev_equity = float(portfolio.get("total_equity", self.starting_balance))

        price_resp = self._api_call("GET", f"/api/v1/market/price/{self.symbol}")
        self._last_step_result = {
            "portfolio": portfolio,
            "prices": {self.symbol: price_resp.get("price", "0")},
            "is_complete": False,
        }
        self._last_step_time = time.time()

        obs = self._get_observation()
        info = {"session_id": "live", "step": 0, "equity": self._prev_equity}
        return obs, info

    def step(
        self, action: Any
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Wait for next candle, execute action, return observation."""
        # Wait for the next interval
        elapsed = time.time() - self._last_step_time
        remaining = self.step_interval_sec - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_step_time = time.time()
        self._step_count += 1

        # Execute action using live trading endpoints
        orders = self._execute_action(action)
        for order in orders:
            try:
                self._api_call("POST", "/api/v1/trade/order", json=order)
            except httpx.HTTPStatusError as exc:
                logger.debug("Live order rejected: %s", exc.response.text)
            except httpx.TransportError as exc:
                logger.warning("Live order transport error: %s", exc)

        # Fetch updated state
        portfolio = self._api_call("GET", "/api/v1/account/portfolio")
        price_resp = self._api_call("GET", f"/api/v1/market/price/{self.symbol}")

        self._last_step_result = {
            "portfolio": portfolio,
            "prices": {self.symbol: price_resp.get("price", "0")},
            "is_complete": False,
        }

        curr_equity = float(portfolio.get("total_equity", self.starting_balance))
        reward = self.reward_fn.compute(self._prev_equity, curr_equity, self._last_step_result)
        self._prev_equity = curr_equity

        obs = self._get_observation()
        info = {
            "session_id": "live",
            "step": self._step_count,
            "equity": curr_equity,
        }

        return obs, reward, False, False, info

    def _execute_action(self, action: Any) -> list[dict[str, Any]]:
        """Translate discrete action to live trading orders."""
        from decimal import Decimal

        orders: list[dict[str, Any]] = []
        portfolio = self._last_step_result.get("portfolio", {})
        equity = float(portfolio.get("total_equity", self.starting_balance))
        price = float(self._last_step_result.get("prices", {}).get(self.symbol, 0))

        if price <= 0:
            return orders

        action_int = int(action)
        if action_int == 1:  # buy
            quantity = Decimal(str(equity * 0.1 / price))
            if quantity > 0:
                orders.append({
                    "symbol": self.symbol,
                    "side": "buy",
                    "type": "market",
                    "quantity": str(quantity),
                })
        elif action_int == 2:  # sell
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
