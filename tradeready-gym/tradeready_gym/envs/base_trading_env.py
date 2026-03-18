"""Base Gymnasium trading environment backed by the TradeReady backtest API."""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import gymnasium as gym
import httpx
import numpy as np
from gymnasium import spaces

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}$")


def _validate_symbol(value: str) -> str:
    """Validate and normalize a trading pair symbol."""
    clean = value.upper().strip()
    if not _SYMBOL_RE.match(clean):
        raise ValueError(f"Invalid symbol: {value!r}. Must be 2-20 alphanumeric chars.")
    return clean


def _validate_base_url(url: str) -> str:
    """Validate base URL for safety (no SSRF to internal services)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsafe base_url scheme: {parsed.scheme!r}")
    if not parsed.netloc:
        raise ValueError("base_url must include a host")
    return url.rstrip("/")

from tradeready_gym.rewards.custom_reward import CustomReward
from tradeready_gym.rewards.pnl_reward import PnLReward
from tradeready_gym.spaces.observation_builders import ObservationBuilder
from tradeready_gym.utils.training_tracker import TrainingTracker

logger = logging.getLogger(__name__)


class BaseTradingEnv(gym.Env):
    """Abstract base class for TradeReady Gymnasium environments.

    Wraps the TradeReady backtest REST API as a Gymnasium environment.
    Each ``reset()`` creates a new backtest session; each ``step()``
    advances the simulation by one candle and translates the agent's
    action into trading orders.

    Args:
        api_key:             TradeReady API key for authentication.
        base_url:            Base URL of the TradeReady REST API.
        starting_balance:    Virtual USDT starting balance per episode.
        timeframe:           Candle interval (e.g. ``"1m"``, ``"5m"``, ``"1h"``).
        lookback_window:     Number of historical candles in the observation.
        reward_function:     Reward calculator (defaults to ``PnLReward``).
        observation_features: List of feature names for the observation builder.
        pairs:               Trading pairs for this environment.
        start_time:          Backtest start time (ISO 8601 string).
        end_time:            Backtest end time (ISO 8601 string).
        track_training:      Whether to report episodes to the training API.
        strategy_label:      Label for backtest sessions (default ``"gym_training"``).
    """

    metadata = {"render_modes": ["human", "ansi"]}

    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
        starting_balance: float = 10000.0,
        timeframe: str = "1m",
        lookback_window: int = 30,
        reward_function: CustomReward | None = None,
        observation_features: list[str] | None = None,
        pairs: list[str] | None = None,
        start_time: str = "2025-01-01T00:00:00Z",
        end_time: str = "2025-02-01T00:00:00Z",
        track_training: bool = True,
        strategy_label: str = "gym_training",
        render_mode: str | None = None,
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self.base_url = _validate_base_url(base_url)
        # Note: starting_balance is kept as float for RL framework compatibility
        # (SB3, numpy). API calls convert via str(Decimal(str(...))) to avoid
        # float precision issues.
        self.starting_balance = float(starting_balance)
        self.timeframe = timeframe
        self.lookback_window = lookback_window
        self.reward_fn = reward_function or PnLReward()
        self.pairs = [_validate_symbol(p) for p in (pairs or ["BTCUSDT"])]
        self.start_time = start_time
        self.end_time = end_time
        self.strategy_label = strategy_label
        self.render_mode = render_mode

        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=30.0,
            headers={"X-API-Key": self._api_key},
        )

        self._obs_builder = ObservationBuilder(
            features=observation_features or ["ohlcv", "rsi_14", "macd", "balance", "position"],
            lookback_window=lookback_window,
            n_assets=len(self.pairs),
        )

        self.observation_space = self._obs_builder.observation_space
        self.action_space: spaces.Space = spaces.Discrete(3)  # overridden by subclasses

        self._session_id: str | None = None
        self._prev_equity: float = starting_balance
        self._step_count: int = 0
        self._episode_count: int = 0
        self._last_step_result: dict[str, Any] = {}

        self._tracker: TrainingTracker | None = None
        if track_training:
            self._tracker = TrainingTracker(
                api_key=api_key,
                base_url=base_url,
                strategy_label=strategy_label,
            )

    def _api_call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated API call."""
        response = self._http.request(method, path, params=params, json=json)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def _create_session(self) -> str:
        """Create and start a new backtest session."""
        _interval_map = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
        body: dict[str, Any] = {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "starting_balance": str(Decimal(str(self.starting_balance))),
            "candle_interval": _interval_map.get(self.timeframe, 60),
            "pairs": self.pairs,
            "strategy_label": self.strategy_label,
        }
        data = self._api_call("POST", "/api/v1/backtest/create", json=body)
        session_id = data["session_id"]
        self._api_call("POST", f"/api/v1/backtest/{session_id}/start")
        return session_id

    def _get_observation(self) -> np.ndarray:
        """Fetch candle + portfolio data and build observation array."""
        candle_data: dict[str, list[dict[str, Any]]] = {}
        for pair in self.pairs:
            resp = self._api_call(
                "GET",
                f"/api/v1/backtest/{self._session_id}/market/candles/{pair}",
                params={"interval": self.timeframe, "limit": self.lookback_window},
            )
            candle_data[pair] = resp.get("candles", [])

        portfolio = self._last_step_result.get("portfolio", {})
        return self._obs_builder.build(candle_data, portfolio)

    def _execute_action(self, action: Any) -> list[dict[str, Any]]:
        """Translate agent action to API orders. Overridden by subclasses."""
        raise NotImplementedError

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Create a new backtest session and return the initial observation."""
        super().reset(seed=seed, options=options)
        self._session_id = self._create_session()
        self._prev_equity = self.starting_balance
        self._step_count = 0
        self._episode_count += 1
        self.reward_fn.reset()

        # Take the first step to populate prices
        self._last_step_result = self._api_call(
            "POST", f"/api/v1/backtest/{self._session_id}/step"
        )

        obs = self._get_observation()
        info = {
            "session_id": self._session_id,
            "step": 0,
            "equity": self.starting_balance,
        }

        if self._tracker:
            self._tracker.register_run()  # idempotent

        return obs, info

    def step(
        self, action: Any
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Execute one environment step: advance time, place orders, compute reward."""
        self._step_count += 1

        # Execute the agent's trading action
        orders = self._execute_action(action)
        for order in orders:
            try:
                self._api_call(
                    "POST",
                    f"/api/v1/backtest/{self._session_id}/trade/order",
                    json=order,
                )
            except httpx.HTTPStatusError as exc:
                logger.debug("Order rejected: %s", exc.response.text)

        # Advance time by one candle
        step_result = self._api_call(
            "POST", f"/api/v1/backtest/{self._session_id}/step"
        )
        self._last_step_result = step_result

        portfolio = step_result.get("portfolio", {})
        curr_equity = float(portfolio.get("total_equity", self.starting_balance))

        # Compute reward
        reward = self.reward_fn.compute(self._prev_equity, curr_equity, step_result)
        self._prev_equity = curr_equity

        terminated = bool(step_result.get("is_complete", False))
        truncated = False

        obs = self._get_observation()
        info = {
            "session_id": self._session_id,
            "step": self._step_count,
            "equity": curr_equity,
            "prices": step_result.get("prices", {}),
            "filled_orders": step_result.get("filled_orders", []),
        }

        if terminated and self._tracker:
            results = self._get_episode_results()
            self._tracker.report_episode(
                episode_number=self._episode_count,
                session_id=self._session_id,
                metrics=results,
            )

        return obs, reward, terminated, truncated, info

    def _get_episode_results(self) -> dict[str, Any]:
        """Fetch final backtest metrics for the current episode."""
        try:
            return self._api_call(
                "GET", f"/api/v1/backtest/{self._session_id}/results"
            )
        except httpx.HTTPStatusError:
            return {}

    def render(self) -> str | None:
        """Render current state as text."""
        if self.render_mode == "human" or self.render_mode == "ansi":
            portfolio = self._last_step_result.get("portfolio", {})
            equity = portfolio.get("total_equity", "?")
            step = self._last_step_result.get("step", "?")
            total = self._last_step_result.get("total_steps", "?")
            text = f"Step {step}/{total} | Equity: {equity} USDT"
            if self.render_mode == "human":
                print(text)  # noqa: T201
            return text
        return None

    def close(self) -> None:
        """Clean up resources and finalize training tracking."""
        if self._tracker:
            self._tracker.complete_run()
        self._http.close()
        super().close()
