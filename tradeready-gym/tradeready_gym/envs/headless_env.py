"""Headless Gymnasium trading environment — zero HTTP overhead.

``HeadlessTradingEnv`` imports the platform's ``BacktestEngine``,
``BacktestSandbox``, and ``DataReplayer`` directly and drives them
in-process.  There is no HTTP client, no JSON serialisation, and no
network latency — all engine calls happen in the same process that
runs the RL training loop.

This environment is designed for same-machine training where the
platform source tree is importable (i.e. ``src/`` is on ``PYTHONPATH``).
It requires a PostgreSQL connection string pointing at the TimescaleDB
instance that holds the candle data.

Gymnasium is a synchronous API; the engine is async.  We bridge the
gap by creating a private ``asyncio`` event loop per env instance and
running every coroutine with ``loop.run_until_complete()``.  We avoid
``asyncio.run()`` because SB3 spawns multiple envs inside threads that
share a process — a dedicated per-env loop is thread-safe without
coordination overhead.

Usage::

    import gymnasium as gym
    import tradeready_gym  # triggers registration

    env = gym.make(
        "TradeReady-BTC-Headless-v0",
        db_url="postgresql+asyncpg://user:pass@localhost/tradeready",
        start_time="2025-01-01T00:00:00Z",
        end_time="2025-02-01T00:00:00Z",
    )
    obs, info = env.reset()
    for _ in range(1000):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            obs, info = env.reset()
    env.close()
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from tradeready_gym.rewards.custom_reward import CustomReward
from tradeready_gym.rewards.pnl_reward import PnLReward
from tradeready_gym.spaces.observation_builders import ObservationBuilder

logger = logging.getLogger(__name__)

# Candle interval strings → seconds
_TIMEFRAME_TO_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


class HeadlessTradingEnv(gym.Env):
    """Single-asset backtest environment backed by direct engine calls.

    Unlike :class:`BaseTradingEnv`, which communicates with the platform
    over HTTP, this environment imports ``BacktestEngine`` and its
    dependencies directly and executes all simulation in-process.  The
    result is zero network latency and zero JSON serialisation overhead
    per step — a significant advantage for long RL training runs.

    The action space and observation space are identical to
    :class:`~tradeready_gym.envs.single_asset_env.SingleAssetTradingEnv`
    so existing wrappers and RL configs work without modification.

    Args:
        db_url:              SQLAlchemy async database URL, e.g.
                             ``"postgresql+asyncpg://user:pass@host/db"``.
        symbol:              Trading pair to simulate (default ``"BTCUSDT"``).
        starting_balance:    Virtual USDT per episode (default ``10000.0``).
        timeframe:           Candle interval; must be one of ``"1m"``,
                             ``"5m"``, ``"15m"``, ``"1h"``, ``"4h"``,
                             ``"1d"`` (default ``"1m"``).
        lookback_window:     Number of historical candles in the observation
                             (default ``30``).
        episode_length:      Maximum number of steps before truncation.
                             ``None`` means run until the time range ends
                             (default ``None``).
        reward_function:     Reward calculator; defaults to
                             :class:`~tradeready_gym.rewards.pnl_reward.PnLReward`.
        observation_features: Feature names passed to
                             :class:`~tradeready_gym.spaces.observation_builders.ObservationBuilder`.
                             Defaults to ``["ohlcv", "rsi_14", "macd", "balance", "position"]``.
        start_time:          Backtest window start (ISO 8601 string,
                             default ``"2025-01-01T00:00:00Z"``).
        end_time:            Backtest window end (ISO 8601 string,
                             default ``"2025-02-01T00:00:00Z"``).
        position_size_pct:   Fraction of equity to allocate per buy trade
                             (default ``0.1`` = 10 %).
        render_mode:         ``"human"`` or ``"ansi"`` or ``None``.
    """

    metadata = {"render_modes": ["human", "ansi"]}

    def __init__(
        self,
        db_url: str,
        symbol: str = "BTCUSDT",
        starting_balance: float = 10000.0,
        timeframe: str = "1m",
        lookback_window: int = 30,
        episode_length: int | None = None,
        reward_function: CustomReward | None = None,
        observation_features: list[str] | None = None,
        start_time: str = "2025-01-01T00:00:00Z",
        end_time: str = "2025-02-01T00:00:00Z",
        position_size_pct: float = 0.1,
        render_mode: str | None = None,
    ) -> None:
        super().__init__()

        self.db_url = db_url
        self.symbol = symbol.upper().strip()
        # Note: stored as float for RL framework compatibility (numpy / SB3).
        # Converted to Decimal(str(...)) at engine boundaries.
        self.starting_balance = float(starting_balance)
        self.timeframe = timeframe
        self.lookback_window = lookback_window
        self.episode_length = episode_length
        self.reward_fn = reward_function or PnLReward()
        self.start_time = start_time
        self.end_time = end_time
        self.position_size_pct = float(position_size_pct)
        self.render_mode = render_mode

        candle_interval = _TIMEFRAME_TO_SECONDS.get(timeframe, 60)
        self._candle_interval = candle_interval

        features = observation_features or ["ohlcv", "rsi_14", "macd", "balance", "position"]
        self._obs_builder = ObservationBuilder(
            features=features,
            lookback_window=lookback_window,
            n_assets=1,
        )
        self.observation_space = self._obs_builder.observation_space
        self.action_space = spaces.Discrete(3)  # 0=Hold, 1=Buy, 2=Sell

        # Per-env private event loop — thread-safe for SB3 SubprocVecEnv.
        self._loop = asyncio.new_event_loop()

        # DB engine and session factory are created lazily on first reset()
        # so that gym.make() does not block waiting for a DB connection.
        self._db_engine: Any = None
        self._session_factory: Any = None

        # Backtest engine instance — one per HeadlessTradingEnv instance so
        # sessions are isolated.
        self._backtest_engine: Any = None

        # Live episode state
        self._session_id: str | None = None
        self._current_prices: dict[str, Decimal] = {}
        self._prev_equity: float = self.starting_balance
        self._step_count: int = 0
        self._episode_count: int = 0
        self._is_done: bool = False

        # Cached last step info for render() and observation building
        self._last_portfolio: dict[str, Any] = {}
        self._last_candles: list[dict[str, Any]] = []

    # ── Gymnasium lifecycle ──────────────────────────────────────────────────

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Create a new in-process backtest session and return the first observation.

        On the very first call this method also initialises the SQLAlchemy
        async engine and the :class:`BacktestEngine` singleton for this env
        instance.  Subsequent calls reuse the same engine and only create a
        new backtest session.

        Args:
            seed:    RNG seed forwarded to :meth:`gymnasium.Env.reset`.
            options: Unused; accepted for API compatibility.

        Returns:
            Tuple of ``(observation, info)``.
        """
        super().reset(seed=seed, options=options)

        self._loop.run_until_complete(self._async_reset())

        obs = self._build_observation()
        info: dict[str, Any] = {
            "session_id": self._session_id,
            "step": 0,
            "equity": self.starting_balance,
            "symbol": self.symbol,
        }
        return obs, info

    def step(self, action: Any) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Advance the simulation by one candle and apply the trading action.

        Args:
            action: An integer in ``{0, 1, 2}``.
                    0 = Hold, 1 = Buy, 2 = Sell (close full position).

        Returns:
            5-tuple: ``(observation, reward, terminated, truncated, info)``.
        """
        result = self._loop.run_until_complete(self._async_step(int(action)))
        return result

    def render(self) -> str | None:
        """Render the current portfolio state as a text string."""
        equity = self._last_portfolio.get("total_equity", "?")
        text = f"Step {self._step_count} | {self.symbol} | Equity: {equity} USDT"
        if self.render_mode == "human":
            print(text)  # noqa: T201
        return text

    def close(self) -> None:
        """Release the database connection pool.

        The event loop is intentionally NOT closed here because SB3's
        ``Monitor`` wrapper may call ``reset()`` after ``close()`` during
        episode transitions.  The loop is only closed in ``__del__`` when
        the env instance is garbage-collected.
        """
        if self._db_engine is not None:
            try:
                if not self._loop.is_closed():
                    self._loop.run_until_complete(self._db_engine.dispose())
            except Exception:  # noqa: BLE001
                logger.debug("headless_env.close: error disposing DB engine", exc_info=True)
            self._db_engine = None
            self._session_factory = None
            self._backtest_engine = None

        super().close()

    def __del__(self) -> None:
        """Ensure the event loop is cleaned up on garbage collection."""
        try:
            if hasattr(self, "_loop") and not self._loop.is_closed():
                self._loop.close()
        except Exception:  # noqa: BLE001
            pass

    # ── Internal async helpers ───────────────────────────────────────────────

    async def _ensure_engine(self) -> None:
        """Lazily initialise the SQLAlchemy async engine and BacktestEngine.

        Importing platform source is deferred to this method so that the
        headless env can be imported in environments where ``src/`` is not
        yet on sys.path (e.g. pure gym package tests).
        """
        if self._db_engine is not None:
            return  # already set up

        # Defer platform imports to avoid circular import issues at module load
        # and to let the gym package be usable without src/ on the path.
        try:
            from sqlalchemy.ext.asyncio import (  # noqa: PLC0415
                AsyncSession,
                async_sessionmaker,
                create_async_engine,
            )
            from src.backtesting.engine import BacktestEngine  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "HeadlessTradingEnv requires the platform source tree on PYTHONPATH "
                "and 'sqlalchemy[asyncio]' plus 'asyncpg' to be installed.\n"
                f"Original error: {exc}"
            ) from exc

        self._db_engine = create_async_engine(
            self.db_url,
            # Keep pool small — each env instance has its own engine.
            pool_size=2,
            max_overflow=0,
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(
            self._db_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self._backtest_engine = BacktestEngine(session_factory=self._session_factory)

    async def _async_reset(self) -> None:
        """Async implementation of reset() — creates and starts a new session."""
        await self._ensure_engine()

        # Imports deferred to match _ensure_engine() pattern
        from src.backtesting.engine import BacktestConfig  # noqa: PLC0415

        # Parse ISO-8601 strings to timezone-aware datetimes
        start_dt = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))

        # Create synthetic Account + Agent rows so the engine's FK checks pass.
        from src.database.models import Account, Agent  # noqa: PLC0415

        synthetic_account_id = uuid4()
        synthetic_agent_id = uuid4()

        async with self._session_factory() as db:
            account = Account(
                id=synthetic_account_id,
                display_name="headless_gym",
                email=f"headless-{synthetic_account_id.hex[:8]}@gym.local",
                password_hash="not-a-real-hash",
                api_key=f"ak_headless_{synthetic_account_id.hex[:16]}",
                api_key_hash="not-a-real-hash",
                api_secret_hash="not-a-real-hash",
                starting_balance=Decimal(str(self.starting_balance)),
            )
            db.add(account)
            await db.flush()

            agent = Agent(
                id=synthetic_agent_id,
                account_id=synthetic_account_id,
                display_name="headless_gym_agent",
                api_key=f"ak_agent_headless_{synthetic_agent_id.hex[:16]}",
                api_key_hash="not-a-real-hash",
                starting_balance=Decimal(str(self.starting_balance)),
            )
            db.add(agent)
            await db.commit()

        config = BacktestConfig(
            start_time=start_dt,
            end_time=end_dt,
            starting_balance=Decimal(str(self.starting_balance)),
            candle_interval=self._candle_interval,
            pairs=[self.symbol],
            strategy_label="headless_gym",
            agent_id=synthetic_agent_id,
        )

        async with self._session_factory() as db:
            session_model = await self._backtest_engine.create_session(
                account_id=synthetic_account_id,
                config=config,
                db=db,
            )
            session_id = str(session_model.id)
            await db.commit()

        async with self._session_factory() as db:
            await self._backtest_engine.start(session_id, db)
            await db.commit()

        self._session_id = session_id
        self._prev_equity = self.starting_balance
        self._step_count = 0
        self._episode_count += 1
        self._is_done = False
        self._last_portfolio = {}
        self._last_candles = []
        self.reward_fn.reset()

        # Take the first step to populate prices and portfolio state
        await self._advance_step()

    async def _advance_step(self) -> None:
        """Call engine.step() and cache the result for observation building."""
        from src.backtesting.engine import StepResult  # noqa: PLC0415

        assert self._session_id is not None  # noqa: S101

        async with self._session_factory() as db:
            step_result: StepResult = await self._backtest_engine.step(self._session_id, db)
            await db.commit()

        self._current_prices = dict(step_result.prices)
        self._is_done = step_result.is_complete
        self._last_portfolio = self._portfolio_to_dict(step_result.portfolio)

        # Fetch candles for observation (no DB hit — served from in-memory cache)
        await self._refresh_candles()

    async def _refresh_candles(self) -> None:
        """Fetch recent candles from the in-memory replayer cache."""
        if self._session_id is None or self._session_id not in self._backtest_engine._active:
            return

        active = self._backtest_engine._active[self._session_id]
        candles = await active.replayer.load_candles(
            self.symbol,
            active.simulator.current_time,
            self._candle_interval,
            self.lookback_window,
        )
        self._last_candles = self._candles_to_dicts(candles)

    async def _async_step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Async implementation of step()."""
        self._step_count += 1

        # Apply the trading action (may place an order into the sandbox)
        self._apply_action(action)

        # Advance virtual clock by one candle
        await self._advance_step()

        portfolio = self._last_portfolio
        curr_equity = float(portfolio.get("total_equity", self.starting_balance))

        reward = float(self.reward_fn.compute(self._prev_equity, curr_equity, portfolio))
        self._prev_equity = curr_equity

        terminated = self._is_done
        truncated = self.episode_length is not None and self._step_count >= self.episode_length

        obs = self._build_observation()
        info: dict[str, Any] = {
            "session_id": self._session_id,
            "step": self._step_count,
            "equity": curr_equity,
            "prices": {k: float(v) for k, v in self._current_prices.items()},
        }
        return obs, reward, terminated, truncated, info

    # ── Trading action logic ─────────────────────────────────────────────────

    def _apply_action(self, action: int) -> None:
        """Translate a discrete action to a sandbox order (or no-op for hold).

        Args:
            action: 0=Hold, 1=Buy, 2=Sell.
        """
        if action == 0:
            return  # hold — nothing to do

        if self._session_id is None or self._session_id not in self._backtest_engine._active:
            return

        active = self._backtest_engine._active[self._session_id]
        current_price = self._current_prices.get(self.symbol, Decimal("0"))
        if current_price <= Decimal("0"):
            return

        portfolio = active.sandbox.get_portfolio(self._current_prices)
        equity = float(portfolio.total_equity)

        if action == 1:  # buy
            trade_value = equity * self.position_size_pct
            quantity = Decimal(str(trade_value)) / current_price
            quantity = quantity.quantize(Decimal("0.00000001"))
            if quantity <= Decimal("0"):
                return
            try:
                active.sandbox.place_order(
                    symbol=self.symbol,
                    side="buy",
                    order_type="market",
                    quantity=quantity,
                    price=None,
                    current_prices=self._current_prices,
                    virtual_time=active.simulator.current_time,
                )
            except Exception:  # noqa: BLE001
                logger.debug("headless_env: buy order rejected", exc_info=True)

        elif action == 2:  # sell — close full position
            positions = active.sandbox.get_positions()
            for pos in positions:
                if pos.symbol == self.symbol and pos.quantity > Decimal("0"):
                    try:
                        active.sandbox.place_order(
                            symbol=self.symbol,
                            side="sell",
                            order_type="market",
                            quantity=pos.quantity,
                            price=None,
                            current_prices=self._current_prices,
                            virtual_time=active.simulator.current_time,
                        )
                    except Exception:  # noqa: BLE001
                        logger.debug("headless_env: sell order rejected", exc_info=True)
                    break

    # ── Observation building ─────────────────────────────────────────────────

    def _build_observation(self) -> np.ndarray:
        """Build the flat observation array from cached candle and portfolio data."""
        candle_data = {self.symbol: self._last_candles}
        return self._obs_builder.build(candle_data, self._last_portfolio)

    # ── Data-format helpers ──────────────────────────────────────────────────

    @staticmethod
    def _portfolio_to_dict(portfolio: Any) -> dict[str, Any]:
        """Convert a ``PortfolioSummary`` dataclass to a plain dict.

        The :class:`~tradeready_gym.spaces.observation_builders.ObservationBuilder`
        expects a plain dict with string keys.  We convert ``Decimal`` values
        to ``float`` here because numpy only understands floats.
        """
        positions_raw = getattr(portfolio, "positions", [])
        positions_out = []
        for p in positions_raw:
            if isinstance(p, dict):
                positions_out.append(p)
            else:
                # SandboxPosition dataclass
                positions_out.append(
                    {
                        "symbol": getattr(p, "symbol", ""),
                        "quantity": float(getattr(p, "quantity", 0)),
                        "avg_entry_price": float(getattr(p, "avg_entry_price", 0)),
                        "total_cost": float(getattr(p, "total_cost", 0)),
                        "realized_pnl": float(getattr(p, "realized_pnl", 0)),
                    }
                )

        return {
            "total_equity": float(getattr(portfolio, "total_equity", 0)),
            "available_cash": float(getattr(portfolio, "available_cash", 0)),
            "total_position_value": float(getattr(portfolio, "position_value", 0)),
            "unrealized_pnl": float(getattr(portfolio, "unrealized_pnl", 0)),
            "realized_pnl": float(getattr(portfolio, "realized_pnl", 0)),
            "starting_balance": 0.0,  # filled on first real step from self.starting_balance
            "positions": positions_out,
        }

    @staticmethod
    def _candles_to_dicts(candles: list[Any]) -> list[dict[str, Any]]:
        """Convert ``Candle`` dataclasses to plain dicts for ObservationBuilder."""
        result = []
        for c in candles:
            if isinstance(c, dict):
                result.append(c)
            else:
                result.append(
                    {
                        "open": float(getattr(c, "open", 0)),
                        "high": float(getattr(c, "high", 0)),
                        "low": float(getattr(c, "low", 0)),
                        "close": float(getattr(c, "close", 0)),
                        "volume": float(getattr(c, "volume", 0)),
                        "bucket": str(getattr(c, "bucket", "")),
                    }
                )
        return result
