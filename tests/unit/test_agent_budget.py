"""Tests for agent/permissions/budget.py.

Covers: BudgetManager.check_budget (all four denial paths + allow path),
record_trade, record_loss, get_budget_status, reset_daily, Redis failure
fallback to DB, _BudgetLimits serialisation, _seconds_until_midnight_utc.
"""

from __future__ import annotations

from decimal import Decimal
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from redis.exceptions import RedisError

from agent.models.ecosystem import BudgetStatus
from agent.permissions.budget import (
    BudgetManager,
    _BudgetLimits,
    _exposure_key,
    _loss_key,
    _seconds_until_midnight_utc,
    _trades_key,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    max_trades: int = 10,
    max_exposure_pct: float = 50.0,
    max_daily_loss_pct: float = 5.0,
) -> MagicMock:
    cfg = MagicMock()
    cfg.default_max_trades_per_day = max_trades
    cfg.default_max_exposure_pct = max_exposure_pct
    cfg.default_max_daily_loss_pct = max_daily_loss_pct
    cfg.default_agent_role = "paper_trader"
    return cfg


def _make_limits(
    max_trades: int = 10,
    max_exposure: str = "5000.00",
    max_loss: str = "500.00",
    max_position: str = "1000.00",
) -> _BudgetLimits:
    return _BudgetLimits(
        max_trades_per_day=max_trades,
        max_exposure_usdt=Decimal(max_exposure),
        max_daily_loss_usdt=Decimal(max_loss),
        max_position_size_usdt=Decimal(max_position),
    )


def _make_budget_manager(
    mock_redis: AsyncMock | None = None,
    config: MagicMock | None = None,
) -> BudgetManager:
    if config is None:
        config = _make_config()
    return BudgetManager(config=config, redis=mock_redis)


def _mock_redis_counters(
    mock_redis: AsyncMock,
    trades: int = 0,
    exposure: str = "0",
    loss: str = "0",
) -> None:
    """Wire mock_redis.mget to return the given counter values."""
    mock_redis.mget.return_value = [
        str(trades).encode() if trades else None,
        exposure.encode() if exposure != "0" else None,
        loss.encode() if loss != "0" else None,
    ]


# ---------------------------------------------------------------------------
# _BudgetLimits serialisation
# ---------------------------------------------------------------------------


class TestBudgetLimitsSerialisation:
    """Tests for _BudgetLimits.to_json and from_json."""

    def test_round_trip(self) -> None:
        """to_json + from_json produces an equivalent _BudgetLimits."""
        original = _make_limits(max_trades=20, max_exposure="2500", max_loss="250", max_position="500")
        restored = _BudgetLimits.from_json(original.to_json())
        assert restored.max_trades_per_day == 20
        assert restored.max_exposure_usdt == Decimal("2500")
        assert restored.max_daily_loss_usdt == Decimal("250")
        assert restored.max_position_size_usdt == Decimal("500")

    def test_to_json_produces_valid_json(self) -> None:
        """to_json output is parseable JSON with the expected keys."""
        limits = _make_limits()
        data = json.loads(limits.to_json())
        assert "max_trades_per_day" in data
        assert "max_exposure_usdt" in data
        assert "max_daily_loss_usdt" in data
        assert "max_position_size_usdt" in data


# ---------------------------------------------------------------------------
# _seconds_until_midnight_utc
# ---------------------------------------------------------------------------


class TestSecondsUntilMidnight:
    """Tests for the _seconds_until_midnight_utc helper."""

    def test_returns_positive_integer(self) -> None:
        """The function returns at least 1 second."""
        secs = _seconds_until_midnight_utc()
        assert isinstance(secs, int)
        assert secs >= 1

    def test_maximum_is_86400(self) -> None:
        """The TTL cannot exceed one full day in seconds."""
        secs = _seconds_until_midnight_utc()
        assert secs <= 86400


# ---------------------------------------------------------------------------
# BudgetManager.check_budget — denial paths
# ---------------------------------------------------------------------------


class TestCheckBudgetDenials:
    """Tests that verify every denial path in check_budget."""

    def setup_method(self) -> None:
        self.mock_redis = AsyncMock()
        self.agent_id = str(uuid4())
        self.manager = _make_budget_manager(mock_redis=self.mock_redis)

    async def _setup_limits_cache(self, limits: _BudgetLimits) -> None:
        """Configure mock_redis to return limits JSON on get()."""
        self.mock_redis.get.side_effect = lambda key: (limits.to_json().encode() if "limits" in key else None)

    async def test_denied_position_size_exceeded(self) -> None:
        """Trade value above max_position_size_usdt is denied with a clear reason."""
        limits = _make_limits(max_position="500.00")
        await self._setup_limits_cache(limits)
        # Counters at zero — return None to use zero defaults
        self.mock_redis.mget.return_value = [None, None, None]

        result = await self.manager.check_budget(self.agent_id, Decimal("600.00"))

        assert result.allowed is False
        assert "position size" in result.reason.lower()
        assert result.remaining_trades >= 0

    async def test_denied_daily_trade_count_exhausted(self) -> None:
        """trades_today >= max_trades_per_day is denied with a clear reason."""
        limits = _make_limits(max_trades=5, max_position="2000.00")
        await self._setup_limits_cache(limits)
        self.mock_redis.mget.return_value = ["5", None, None]  # trades_today == limit

        result = await self.manager.check_budget(self.agent_id, Decimal("100.00"))

        assert result.allowed is False
        assert "daily trade limit" in result.reason.lower() or "trade limit" in result.reason.lower()
        assert result.remaining_trades == 0

    async def test_denied_exposure_cap_exceeded(self) -> None:
        """New trade that would push exposure past the cap is denied."""
        limits = _make_limits(max_trades=10, max_exposure="1000.00", max_position="2000.00")
        await self._setup_limits_cache(limits)
        # Current exposure is 800; adding 300 would push it to 1100 > 1000
        self.mock_redis.mget.return_value = ["2", "800.00", None]

        result = await self.manager.check_budget(self.agent_id, Decimal("300.00"))

        assert result.allowed is False
        assert "exposure" in result.reason.lower()

    async def test_denied_daily_loss_limit_reached(self) -> None:
        """loss_today >= max_daily_loss_usdt fires the circuit breaker."""
        limits = _make_limits(max_trades=10, max_loss="200.00", max_position="2000.00")
        await self._setup_limits_cache(limits)
        # Loss equals limit exactly
        self.mock_redis.mget.return_value = ["3", "100.00", "200.00"]

        result = await self.manager.check_budget(self.agent_id, Decimal("50.00"))

        assert result.allowed is False
        assert "loss limit" in result.reason.lower()
        assert result.remaining_loss_budget == Decimal("0")

    async def test_check_budget_allowed_returns_correct_headroom(self) -> None:
        """Allowed check returns correct remaining headroom values."""
        limits = _make_limits(max_trades=10, max_exposure="5000.00", max_loss="500.00", max_position="1000.00")
        await self._setup_limits_cache(limits)
        # 2 trades used, 500 exposure, 50 loss
        self.mock_redis.mget.return_value = ["2", "500.00", "50.00"]

        result = await self.manager.check_budget(self.agent_id, Decimal("100.00"))

        assert result.allowed is True
        assert result.reason == ""
        assert result.remaining_trades == 7  # 10 - 2 - 1 prospective
        assert result.remaining_exposure == Decimal("4400.00")  # 5000 - 500 - 100
        assert result.remaining_loss_budget == Decimal("450.00")  # 500 - 50

    async def test_denial_reason_is_non_empty_string(self) -> None:
        """Denied results always have a non-empty human-readable reason."""
        limits = _make_limits(max_trades=0, max_position="2000.00")
        await self._setup_limits_cache(limits)
        self.mock_redis.mget.return_value = ["0", None, None]

        result = await self.manager.check_budget(self.agent_id, Decimal("100.00"))

        # trades_today (0) >= max_trades_per_day (0) → denied
        assert result.allowed is False
        assert len(result.reason) > 0


# ---------------------------------------------------------------------------
# BudgetManager.record_trade
# ---------------------------------------------------------------------------


class TestRecordTrade:
    """Tests for BudgetManager.record_trade."""

    def setup_method(self) -> None:
        self.agent_id = str(uuid4())
        self.mock_redis = AsyncMock()

        # Pipeline mock — pipeline() must be MagicMock (sync call), pipe context is async
        self.mock_pipe = MagicMock()
        self.mock_pipe.incr = MagicMock()
        self.mock_pipe.expire = MagicMock()
        self.mock_pipe.incrbyfloat = MagicMock()
        self.mock_pipe.execute = AsyncMock(return_value=[1, True, 500.0, True])
        self.mock_pipe.__aenter__ = AsyncMock(return_value=self.mock_pipe)
        self.mock_pipe.__aexit__ = AsyncMock(return_value=False)
        self.mock_redis.pipeline = MagicMock(return_value=self.mock_pipe)

        self.manager = _make_budget_manager(mock_redis=self.mock_redis)

    async def test_record_trade_increments_trades_and_exposure(self) -> None:
        """record_trade calls incr on trades key and incrbyfloat on exposure key."""
        with patch("agent.permissions.budget.asyncio.ensure_future"):
            await self.manager.record_trade(self.agent_id, Decimal("250.00"))

        self.mock_pipe.incr.assert_called_once_with(_trades_key(self.agent_id))
        # budget.py uses format(trade_value, "f") → produces a decimal string like "250.00"
        self.mock_pipe.incrbyfloat.assert_called_once_with(_exposure_key(self.agent_id), format(Decimal("250.00"), "f"))

    async def test_record_trade_redis_error_is_logged_not_raised(self) -> None:
        """RedisError in record_trade is caught and does not raise."""
        self.mock_pipe.__aenter__.side_effect = RedisError("pipe failed")
        # Should not raise
        with patch("agent.permissions.budget.asyncio.ensure_future"):
            await self.manager.record_trade(self.agent_id, Decimal("100.00"))


# ---------------------------------------------------------------------------
# BudgetManager.record_loss
# ---------------------------------------------------------------------------


class TestRecordLoss:
    """Tests for BudgetManager.record_loss."""

    def setup_method(self) -> None:
        self.agent_id = str(uuid4())
        self.mock_redis = AsyncMock()

        self.mock_pipe = MagicMock()
        self.mock_pipe.incrbyfloat = MagicMock()
        self.mock_pipe.expire = MagicMock()
        self.mock_pipe.execute = AsyncMock(return_value=[50.0, True])
        self.mock_pipe.__aenter__ = AsyncMock(return_value=self.mock_pipe)
        self.mock_pipe.__aexit__ = AsyncMock(return_value=False)
        self.mock_redis.pipeline = MagicMock(return_value=self.mock_pipe)

        self.manager = _make_budget_manager(mock_redis=self.mock_redis)

    async def test_record_loss_increments_loss_key(self) -> None:
        """record_loss calls incrbyfloat on the loss key."""
        with patch("agent.permissions.budget.asyncio.ensure_future"):
            await self.manager.record_loss(self.agent_id, Decimal("45.00"))

        # budget.py uses format(loss_amount, "f") → decimal string
        self.mock_pipe.incrbyfloat.assert_called_once_with(_loss_key(self.agent_id), format(Decimal("45.00"), "f"))

    async def test_record_loss_zero_or_negative_is_skipped(self) -> None:
        """record_loss silently skips non-positive loss amounts."""
        with patch("agent.permissions.budget.asyncio.ensure_future"):
            await self.manager.record_loss(self.agent_id, Decimal("0"))
            await self.manager.record_loss(self.agent_id, Decimal("-10"))

        # Pipeline should not be called for zero/negative amounts
        self.mock_pipe.incrbyfloat.assert_not_called()


# ---------------------------------------------------------------------------
# BudgetManager.get_budget_status
# ---------------------------------------------------------------------------


class TestGetBudgetStatus:
    """Tests for BudgetManager.get_budget_status."""

    def setup_method(self) -> None:
        self.mock_redis = AsyncMock()
        self.agent_id = str(uuid4())
        self.manager = _make_budget_manager(mock_redis=self.mock_redis)

    async def test_returns_budget_status_instance(self) -> None:
        """get_budget_status returns a BudgetStatus Pydantic model."""
        limits = _make_limits(max_trades=10, max_exposure="5000.00", max_loss="500.00")
        self.mock_redis.get.side_effect = lambda key: (limits.to_json().encode() if "limits" in key else None)
        self.mock_redis.mget.return_value = ["3", "1500.00", "75.00"]

        status = await self.manager.get_budget_status(self.agent_id)

        assert isinstance(status, BudgetStatus)
        assert status.agent_id == self.agent_id
        assert status.trades_today == 3
        assert status.trades_limit == 10

    async def test_utilisation_percentages_are_correct(self) -> None:
        """Utilisation fractions are computed correctly from counters and limits."""
        limits = _make_limits(max_trades=10, max_exposure="1000.00", max_loss="500.00")
        self.mock_redis.get.side_effect = lambda key: (limits.to_json().encode() if "limits" in key else None)
        self.mock_redis.mget.return_value = ["5", "500.00", "250.00"]

        status = await self.manager.get_budget_status(self.agent_id)

        assert abs(status.trades_utilization_pct - 0.5) < 1e-6
        assert abs(status.exposure_utilization_pct - 0.5) < 1e-6
        assert abs(status.loss_utilization_pct - 0.5) < 1e-6

    async def test_utilisation_clamped_to_one_when_over_limit(self) -> None:
        """Utilisation fraction is clamped to 1.0 when counters exceed limits."""
        limits = _make_limits(max_trades=5, max_exposure="100.00", max_loss="50.00")
        self.mock_redis.get.side_effect = lambda key: (limits.to_json().encode() if "limits" in key else None)
        # All counters exceed their limits
        self.mock_redis.mget.return_value = ["10", "999.00", "999.00"]

        status = await self.manager.get_budget_status(self.agent_id)

        assert status.trades_utilization_pct <= 1.0
        assert status.exposure_utilization_pct <= 1.0
        assert status.loss_utilization_pct <= 1.0


# ---------------------------------------------------------------------------
# BudgetManager.reset_daily
# ---------------------------------------------------------------------------


class TestResetDaily:
    """Tests for BudgetManager.reset_daily."""

    def setup_method(self) -> None:
        self.agent_id = str(uuid4())
        self.mock_redis = AsyncMock()

        self.mock_pipe = MagicMock()
        self.mock_pipe.delete = MagicMock()
        self.mock_pipe.execute = AsyncMock(return_value=[1, 1, 1, 1])
        self.mock_pipe.__aenter__ = AsyncMock(return_value=self.mock_pipe)
        self.mock_pipe.__aexit__ = AsyncMock(return_value=False)
        self.mock_redis.pipeline = MagicMock(return_value=self.mock_pipe)

    async def test_reset_daily_deletes_redis_counter_keys(self) -> None:
        """reset_daily deletes all four counter/last_persist Redis keys."""
        from src.database.repositories.agent_budget_repo import AgentBudgetNotFoundError  # noqa: PLC0415

        mock_repo = AsyncMock()
        mock_repo.reset_daily.side_effect = AgentBudgetNotFoundError("no record")

        mock_session = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin.return_value = mock_session_cm

        config = _make_config()
        manager = _make_budget_manager(mock_redis=self.mock_redis, config=config)

        with (
            patch("src.database.repositories.agent_budget_repo.AgentBudgetRepository", return_value=mock_repo),
            patch.object(manager, "_get_db_session", new=AsyncMock(return_value=mock_session)),
        ):
            await manager.reset_daily(self.agent_id)

        # pipeline.delete should have been called 4 times (trades, exposure, loss, last_persist)
        assert self.mock_pipe.delete.call_count == 4

    async def test_reset_daily_redis_error_does_not_raise(self) -> None:
        """RedisError during reset_daily does not propagate to the caller."""
        self.mock_pipe.__aenter__.side_effect = RedisError("failed")

        from src.database.repositories.agent_budget_repo import AgentBudgetNotFoundError  # noqa: PLC0415

        mock_repo = AsyncMock()
        mock_repo.reset_daily.side_effect = AgentBudgetNotFoundError("no record")

        mock_session = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin.return_value = mock_session_cm

        config = _make_config()
        manager = _make_budget_manager(mock_redis=self.mock_redis, config=config)

        with (
            patch("src.database.repositories.agent_budget_repo.AgentBudgetRepository", return_value=mock_repo),
            patch.object(manager, "_get_db_session", new=AsyncMock(return_value=mock_session)),
        ):
            # Should not raise even though Redis fails
            await manager.reset_daily(self.agent_id)


# ---------------------------------------------------------------------------
# BudgetManager — Redis failure fallback to DB
# ---------------------------------------------------------------------------


class TestBudgetManagerRedisFailureFallback:
    """BudgetManager falls back to Postgres when Redis is unavailable."""

    def setup_method(self) -> None:
        self.agent_id = str(uuid4())

    async def test_counter_read_redis_error_falls_back_to_db(self) -> None:
        """RedisError on mget falls back to DB counters without raising."""
        mock_redis = AsyncMock()
        # Redis throws on limits get (so we use config defaults)
        mock_redis.get.side_effect = RedisError("unavailable")
        # Redis throws on mget (counter read)
        mock_redis.mget.side_effect = RedisError("unavailable")

        mock_budget_row = MagicMock()
        mock_budget_row.trades_today = 2
        mock_budget_row.exposure_today = Decimal("200.00")
        mock_budget_row.loss_today = Decimal("10.00")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.get_by_agent.return_value = mock_budget_row

        config = _make_config()
        manager = BudgetManager(config=config, redis=mock_redis)

        with (
            patch("src.database.repositories.agent_budget_repo.AgentBudgetRepository", return_value=mock_repo),
            patch.object(manager, "_get_db_session", new=AsyncMock(return_value=mock_session)),
        ):
            trades, exposure, loss = await manager._read_counters(self.agent_id)

        # Should return DB values, not raise
        assert trades == 2
        assert exposure == Decimal("200.00")
        assert loss == Decimal("10.00")

    async def test_resolve_limits_redis_error_uses_config_defaults(self) -> None:
        """RedisError on limits get falls back to AgentConfig defaults."""
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = RedisError("down")
        mock_redis.set = AsyncMock()

        from src.database.repositories.agent_budget_repo import AgentBudgetNotFoundError  # noqa: PLC0415

        mock_repo = AsyncMock()
        mock_repo.get_by_agent.side_effect = AgentBudgetNotFoundError("no record")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        config = _make_config(max_trades=25, max_exposure_pct=30.0, max_daily_loss_pct=3.0)
        manager = BudgetManager(config=config, redis=mock_redis)

        with (
            patch("src.database.repositories.agent_budget_repo.AgentBudgetRepository", return_value=mock_repo),
            patch.object(manager, "_get_db_session", new=AsyncMock(return_value=mock_session)),
        ):
            limits = await manager._resolve_limits(self.agent_id)

        # Config default: 25 trades/day
        assert limits.max_trades_per_day == 25
        # 30% of 10000 = 3000
        assert limits.max_exposure_usdt == Decimal("3000.00000000")
