"""Tests for agent/strategies/risk/recovery.py — RecoveryManager."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import RedisError

from agent.strategies.risk.recovery import (
    ATR_NORMALISATION_FACTOR,
    RECOVERY_THRESHOLD,
    SCALE_DAYS,
    SCALE_STEP,
    RecoveryConfig,
    RecoveryManager,
    RecoverySnapshot,
    RecoveryState,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_redis() -> MagicMock:
    """Return a mock async Redis client with pipeline support.

    The pipeline is synchronous (MagicMock), but ``pipe.execute`` is an
    AsyncMock so that ``await pipe.execute()`` resolves correctly.
    Following the pattern from ``feedback_redis_pipeline_mock.md``.
    """
    redis = MagicMock()
    pipe = MagicMock()
    pipe.hset = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[True])
    redis.pipeline = MagicMock(return_value=pipe)
    redis.hgetall = AsyncMock(return_value={})
    redis.delete = AsyncMock(return_value=1)
    return redis


def _make_manager(
    redis: MagicMock | None = None,
    config: RecoveryConfig | None = None,
    agent_id: str = "test-agent",
) -> RecoveryManager:
    """Return a RecoveryManager with a mock Redis client."""
    return RecoveryManager(
        agent_id=agent_id,
        redis=redis or _make_redis(),
        config=config,
    )


def _make_snapshot(
    state: RecoveryState = RecoveryState.RECOVERING,
    drawdown_pct: float = 0.12,
    equity_at_trigger: str = "88000",
    peak_equity: str = "100000",
    days_scaling: int = 0,
    current_multiplier: float = 0.0,
) -> RecoverySnapshot:
    """Build a minimal RecoverySnapshot for tests."""
    return RecoverySnapshot(
        state=state,
        drawdown_pct=drawdown_pct,
        equity_at_trigger=equity_at_trigger,
        peak_equity=peak_equity,
        days_scaling=days_scaling,
        current_multiplier=current_multiplier,
        started_at="2026-03-22T00:00:00+00:00",
        last_updated="2026-03-22T00:00:00+00:00",
    )


def _snapshot_as_redis_bytes(snap: RecoverySnapshot) -> dict[bytes, bytes]:
    """Simulate bytes output from redis.hgetall for a given snapshot."""
    return {k.encode(): v.encode() for k, v in snap.to_dict().items()}


# ---------------------------------------------------------------------------
# RecoveryConfig
# ---------------------------------------------------------------------------


class TestRecoveryConfig:
    """Verify RecoveryConfig defaults and validation."""

    def test_defaults_match_constants(self) -> None:
        """RecoveryConfig defaults match module-level constant values."""
        cfg = RecoveryConfig()
        assert cfg.atr_normalisation_factor == ATR_NORMALISATION_FACTOR
        assert cfg.scale_step == SCALE_STEP
        assert cfg.scale_days == SCALE_DAYS
        assert cfg.recovery_threshold == RECOVERY_THRESHOLD

    def test_custom_values_accepted(self) -> None:
        """Custom values override defaults."""
        cfg = RecoveryConfig(atr_normalisation_factor=2.0, scale_step=0.20)
        assert cfg.atr_normalisation_factor == 2.0
        assert cfg.scale_step == 0.20

    def test_atr_factor_le_one_raises(self) -> None:
        """atr_normalisation_factor <= 1.0 is invalid."""
        with pytest.raises(ValueError, match="atr_normalisation_factor"):
            RecoveryConfig(atr_normalisation_factor=1.0)

    def test_atr_factor_below_one_raises(self) -> None:
        """atr_normalisation_factor < 1.0 is invalid."""
        with pytest.raises(ValueError, match="atr_normalisation_factor"):
            RecoveryConfig(atr_normalisation_factor=0.5)

    def test_zero_scale_step_raises(self) -> None:
        """scale_step = 0.0 is invalid."""
        with pytest.raises(ValueError, match="scale_step"):
            RecoveryConfig(scale_step=0.0)

    def test_scale_step_above_one_raises(self) -> None:
        """scale_step > 1.0 is invalid."""
        with pytest.raises(ValueError, match="scale_step"):
            RecoveryConfig(scale_step=1.1)

    def test_scale_days_zero_raises(self) -> None:
        """scale_days = 0 is invalid."""
        with pytest.raises(ValueError, match="scale_days"):
            RecoveryConfig(scale_days=0)

    def test_zero_recovery_threshold_raises(self) -> None:
        """recovery_threshold = 0.0 is invalid."""
        with pytest.raises(ValueError, match="recovery_threshold"):
            RecoveryConfig(recovery_threshold=0.0)

    def test_recovery_threshold_above_one_raises(self) -> None:
        """recovery_threshold > 1.0 is invalid."""
        with pytest.raises(ValueError, match="recovery_threshold"):
            RecoveryConfig(recovery_threshold=1.1)


# ---------------------------------------------------------------------------
# RecoverySnapshot
# ---------------------------------------------------------------------------


class TestRecoverySnapshot:
    """Verify serialisation and helper methods on RecoverySnapshot."""

    def test_to_dict_and_from_dict_roundtrip(self) -> None:
        """Snapshot serialises to dict and back without data loss."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=2,
            current_multiplier=0.50,
        )
        restored = RecoverySnapshot.from_dict(snap.to_dict())
        assert restored.state == snap.state
        assert restored.days_scaling == snap.days_scaling
        assert restored.current_multiplier == snap.current_multiplier
        assert restored.equity_at_trigger == snap.equity_at_trigger
        assert restored.peak_equity == snap.peak_equity

    def test_equity_at_trigger_decimal(self) -> None:
        """equity_at_trigger_decimal returns a Decimal."""
        snap = _make_snapshot(equity_at_trigger="88000")
        assert snap.equity_at_trigger_decimal == Decimal("88000")

    def test_peak_equity_decimal(self) -> None:
        """peak_equity_decimal returns a Decimal."""
        snap = _make_snapshot(peak_equity="100000")
        assert snap.peak_equity_decimal == Decimal("100000")

    def test_recovery_target_50pct(self) -> None:
        """Default 50 % threshold: target = trigger + 50 % of drawdown."""
        # drawdown = 100000 - 88000 = 12000; 50% = 6000; target = 94000
        snap = _make_snapshot(peak_equity="100000", equity_at_trigger="88000")
        assert snap.recovery_target() == Decimal("94000")

    def test_recovery_target_custom_threshold(self) -> None:
        """Custom threshold is applied correctly."""
        snap = _make_snapshot(peak_equity="100000", equity_at_trigger="80000")
        # drawdown = 20000; 75% = 15000; target = 95000
        assert snap.recovery_target(threshold=0.75) == Decimal("95000")

    def test_from_dict_bytes_values(self) -> None:
        """from_dict works with string values (not bytes — decode happens in load)."""
        snap = _make_snapshot()
        data = snap.to_dict()
        # All values are strings in the dict
        assert all(isinstance(v, str) for v in data.values())
        restored = RecoverySnapshot.from_dict(data)
        assert restored.state == snap.state


# ---------------------------------------------------------------------------
# RecoveryManager.load
# ---------------------------------------------------------------------------


class TestRecoveryManagerLoad:
    """RecoveryManager.load reads and decodes Redis state."""

    async def test_load_returns_none_when_no_state(self) -> None:
        """load() returns None when Redis has no stored state."""
        manager = _make_manager()
        result = await manager.load()
        assert result is None

    async def test_load_decodes_bytes_from_redis(self) -> None:
        """load() correctly decodes bytes keys/values from hgetall."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=2,
            current_multiplier=0.50,
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        result = await manager.load()
        assert result is not None
        assert result.state == RecoveryState.SCALING_UP
        assert result.days_scaling == 2

    async def test_load_returns_none_on_redis_error(self) -> None:
        """load() returns None (safe default) when Redis raises."""
        redis = _make_redis()
        redis.hgetall = AsyncMock(side_effect=RedisError("connection refused"))
        manager = _make_manager(redis=redis)

        result = await manager.load()
        assert result is None

    async def test_load_returns_none_on_corrupt_state(self) -> None:
        """load() returns None when stored state is corrupt / missing fields."""
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value={b"state": b"INVALID_STATE"})
        manager = _make_manager(redis=redis)

        result = await manager.load()
        assert result is None


# ---------------------------------------------------------------------------
# RecoveryManager.start_recovery
# ---------------------------------------------------------------------------


class TestStartRecovery:
    """RecoveryManager.start_recovery initiates the machine."""

    async def test_creates_recovering_state(self) -> None:
        """start_recovery transitions to RECOVERING with correct fields."""
        redis = _make_redis()
        manager = _make_manager(redis=redis)

        snap = await manager.start_recovery(
            drawdown_pct=0.12,
            equity_at_trigger=Decimal("88000"),
            peak_equity=Decimal("100000"),
        )

        assert snap.state == RecoveryState.RECOVERING
        assert snap.current_multiplier == 0.0
        assert snap.days_scaling == 0
        assert snap.drawdown_pct == 0.12
        assert snap.equity_at_trigger == "88000"
        assert snap.peak_equity == "100000"

    async def test_persists_to_redis(self) -> None:
        """start_recovery calls pipeline.hset to persist state."""
        redis = _make_redis()
        manager = _make_manager(redis=redis)

        await manager.start_recovery(
            drawdown_pct=0.10,
            equity_at_trigger=Decimal("90000"),
            peak_equity=Decimal("100000"),
        )

        pipe = redis.pipeline.return_value
        pipe.hset.assert_called_once()

    async def test_idempotent_when_already_recovering(self) -> None:
        """start_recovery does not reset progress if already active."""
        existing = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=2,
            current_multiplier=0.50,
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(existing))
        manager = _make_manager(redis=redis)

        snap = await manager.start_recovery(
            drawdown_pct=0.20,
            equity_at_trigger=Decimal("80000"),
            peak_equity=Decimal("100000"),
        )

        # Should return existing state, not reset to new drawdown values
        assert snap.state == RecoveryState.SCALING_UP
        assert snap.days_scaling == 2

    async def test_restarts_when_full(self) -> None:
        """start_recovery creates new recovery if previous is FULL."""
        full_snap = _make_snapshot(
            state=RecoveryState.FULL,
            days_scaling=4,
            current_multiplier=1.0,
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(full_snap))
        manager = _make_manager(redis=redis)

        snap = await manager.start_recovery(
            drawdown_pct=0.15,
            equity_at_trigger=Decimal("85000"),
            peak_equity=Decimal("100000"),
        )

        assert snap.state == RecoveryState.RECOVERING
        assert snap.current_multiplier == 0.0


# ---------------------------------------------------------------------------
# RecoveryManager.get_size_multiplier — no active recovery
# ---------------------------------------------------------------------------


class TestGetSizeMultiplierNoRecovery:
    """get_size_multiplier returns 1.0 when no recovery is active."""

    async def test_returns_one_when_no_state(self) -> None:
        """No Redis state → multiplier is 1.0 (full size)."""
        manager = _make_manager()
        result = await manager.get_size_multiplier(
            current_atr=100.0,
            median_atr=80.0,
            current_equity=Decimal("100000"),
        )
        assert result == 1.0

    async def test_returns_one_when_state_is_full(self) -> None:
        """FULL state → multiplier is 1.0."""
        full_snap = _make_snapshot(state=RecoveryState.FULL, current_multiplier=1.0)
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(full_snap))
        manager = _make_manager(redis=redis)

        result = await manager.get_size_multiplier(
            current_atr=50.0,
            median_atr=80.0,
            current_equity=Decimal("100000"),
        )
        assert result == 1.0


# ---------------------------------------------------------------------------
# RecoveryManager.get_size_multiplier — RECOVERING state
# ---------------------------------------------------------------------------


class TestGetSizeMultiplierRecovering:
    """get_size_multiplier during RECOVERING phase gates on ATR."""

    async def test_returns_zero_when_atr_elevated(self) -> None:
        """When ATR > threshold, multiplier is 0.0 (no trades)."""
        snap = _make_snapshot(state=RecoveryState.RECOVERING)
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        # current_atr = 150 > 1.5 * 80 = 120 → still elevated
        result = await manager.get_size_multiplier(
            current_atr=150.0,
            median_atr=80.0,
            current_equity=Decimal("88000"),
        )
        assert result == 0.0

    async def test_returns_initial_step_when_atr_normalises(self) -> None:
        """When ATR normalises, returns 0.25 and transitions to SCALING_UP."""
        snap = _make_snapshot(state=RecoveryState.RECOVERING)
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        # current_atr = 100 < 1.5 * 80 = 120 → normalised
        result = await manager.get_size_multiplier(
            current_atr=100.0,
            median_atr=80.0,
            current_equity=Decimal("88000"),
        )
        assert result == pytest.approx(0.25)

    async def test_transitions_to_scaling_up_on_atr_normalisation(self) -> None:
        """ATR normalisation persists SCALING_UP state to Redis."""
        snap = _make_snapshot(state=RecoveryState.RECOVERING)
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        await manager.get_size_multiplier(
            current_atr=50.0,
            median_atr=80.0,
            current_equity=Decimal("88000"),
        )

        # Verify pipeline.hset was called (state persisted)
        pipe = redis.pipeline.return_value
        pipe.hset.assert_called()

    async def test_returns_zero_when_median_atr_is_zero(self) -> None:
        """Zero median ATR prevents division; multiplier stays 0.0."""
        snap = _make_snapshot(state=RecoveryState.RECOVERING)
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        result = await manager.get_size_multiplier(
            current_atr=10.0,
            median_atr=0.0,
            current_equity=Decimal("88000"),
        )
        assert result == 0.0

    async def test_custom_atr_factor_applied(self) -> None:
        """Custom atr_normalisation_factor changes the ATR threshold."""
        cfg = RecoveryConfig(atr_normalisation_factor=2.0)
        snap = _make_snapshot(state=RecoveryState.RECOVERING)
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis, config=cfg)

        # With factor=2.0, threshold = 2.0 * 80 = 160
        # current_atr = 150 < 160 → normalised
        result = await manager.get_size_multiplier(
            current_atr=150.0,
            median_atr=80.0,
            current_equity=Decimal("88000"),
        )
        assert result == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# RecoveryManager.get_size_multiplier — SCALING_UP state
# ---------------------------------------------------------------------------


class TestGetSizeMultiplierScalingUp:
    """get_size_multiplier during SCALING_UP phase applies equity gate."""

    async def test_returns_snapshot_multiplier_below_cap(self) -> None:
        """Returns snapshot multiplier when below the equity-gate cap."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            current_multiplier=0.50,
            peak_equity="100000",
            equity_at_trigger="88000",
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        # current_equity below recovery target — but multiplier (0.50) is below cap (0.75)
        result = await manager.get_size_multiplier(
            current_atr=50.0,
            median_atr=80.0,
            current_equity=Decimal("90000"),  # target = 94000
        )
        assert result == pytest.approx(0.50)

    async def test_caps_at_75_when_equity_not_recovered(self) -> None:
        """When multiplier reaches 1.0 before equity target, caps at 0.75."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            current_multiplier=1.0,  # ramp complete but equity not recovered
            peak_equity="100000",
            equity_at_trigger="88000",
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        # current_equity = 90000 < target 94000 → cap at 0.75
        result = await manager.get_size_multiplier(
            current_atr=50.0,
            median_atr=80.0,
            current_equity=Decimal("90000"),
        )
        assert result == pytest.approx(0.75)

    async def test_returns_full_when_equity_recovered(self) -> None:
        """Returns 1.0 when equity has reached the recovery target."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            current_multiplier=1.0,
            peak_equity="100000",
            equity_at_trigger="88000",
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        # target = 88000 + 0.5 * 12000 = 94000; equity 95000 >= 94000 → full
        result = await manager.get_size_multiplier(
            current_atr=50.0,
            median_atr=80.0,
            current_equity=Decimal("95000"),
        )
        assert result == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# RecoveryManager.advance_day
# ---------------------------------------------------------------------------


class TestAdvanceDay:
    """RecoveryManager.advance_day increments the scale-up ramp."""

    async def test_returns_none_when_no_state(self) -> None:
        """advance_day is a no-op when no recovery is active."""
        manager = _make_manager()
        result = await manager.advance_day(
            current_equity=Decimal("95000"),
            had_loss=False,
        )
        assert result is None

    async def test_no_op_in_recovering_state(self) -> None:
        """advance_day does nothing while still in RECOVERING."""
        snap = _make_snapshot(state=RecoveryState.RECOVERING)
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        result = await manager.advance_day(
            current_equity=Decimal("88000"),
            had_loss=False,
        )
        # State should be unchanged (RECOVERING)
        assert result is not None
        assert result.state == RecoveryState.RECOVERING

    async def test_loss_day_skips_advance(self) -> None:
        """A loss day does not increment days_scaling or change multiplier."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=1,
            current_multiplier=0.25,
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        result = await manager.advance_day(
            current_equity=Decimal("88000"),
            had_loss=True,
        )

        assert result is not None
        assert result.days_scaling == 1  # unchanged
        assert result.current_multiplier == 0.25  # unchanged

    async def test_day1_advances_to_0_25(self) -> None:
        """After first qualifying day, multiplier should be 0.25."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=0,
            current_multiplier=0.0,
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        result = await manager.advance_day(
            current_equity=Decimal("88000"),
            had_loss=False,
        )

        assert result is not None
        assert result.days_scaling == 1
        assert result.current_multiplier == pytest.approx(0.25)
        assert result.state == RecoveryState.SCALING_UP

    async def test_day2_advances_to_0_50(self) -> None:
        """After second qualifying day, multiplier should be 0.50."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=1,
            current_multiplier=0.25,
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        result = await manager.advance_day(
            current_equity=Decimal("88000"),
            had_loss=False,
        )

        assert result is not None
        assert result.days_scaling == 2
        assert result.current_multiplier == pytest.approx(0.50)

    async def test_day3_advances_to_0_75(self) -> None:
        """After third qualifying day, multiplier should be 0.75."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=2,
            current_multiplier=0.50,
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        result = await manager.advance_day(
            current_equity=Decimal("88000"),
            had_loss=False,
        )

        assert result is not None
        assert result.days_scaling == 3
        assert result.current_multiplier == pytest.approx(0.75)

    async def test_day4_transitions_to_full_when_equity_recovered(self) -> None:
        """Fourth day with equity above target transitions to FULL."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=3,
            current_multiplier=0.75,
            peak_equity="100000",
            equity_at_trigger="88000",
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        # target = 94000; equity = 95000 ≥ 94000
        result = await manager.advance_day(
            current_equity=Decimal("95000"),
            had_loss=False,
        )

        assert result is not None
        assert result.state == RecoveryState.FULL
        assert result.current_multiplier == pytest.approx(1.0)

    async def test_day4_stays_at_0_75_when_equity_not_recovered(self) -> None:
        """Fourth day but equity below target: capped at 0.75, stays SCALING_UP."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=3,
            current_multiplier=0.75,
            peak_equity="100000",
            equity_at_trigger="88000",
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        # target = 94000; equity = 90000 < 94000
        result = await manager.advance_day(
            current_equity=Decimal("90000"),
            had_loss=False,
        )

        assert result is not None
        assert result.state == RecoveryState.SCALING_UP
        assert result.current_multiplier == pytest.approx(0.75)

    async def test_advances_persisted_to_redis(self) -> None:
        """advance_day persists the updated snapshot via pipeline."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=1,
            current_multiplier=0.25,
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        await manager.advance_day(
            current_equity=Decimal("90000"),
            had_loss=False,
        )

        pipe = redis.pipeline.return_value
        pipe.hset.assert_called()


# ---------------------------------------------------------------------------
# RecoveryManager.complete_recovery
# ---------------------------------------------------------------------------


class TestCompleteRecovery:
    """RecoveryManager.complete_recovery force-completes the machine."""

    async def test_transitions_to_full(self) -> None:
        """complete_recovery sets state FULL and multiplier 1.0."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=2,
            current_multiplier=0.50,
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        result = await manager.complete_recovery()

        assert result is not None
        assert result.state == RecoveryState.FULL
        assert result.current_multiplier == 1.0

    async def test_no_op_when_already_full(self) -> None:
        """complete_recovery returns existing snapshot if already FULL."""
        snap = _make_snapshot(state=RecoveryState.FULL, current_multiplier=1.0)
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        result = await manager.complete_recovery()

        assert result is not None
        assert result.state == RecoveryState.FULL

    async def test_no_op_when_no_active_recovery(self) -> None:
        """complete_recovery returns None if no recovery is active."""
        manager = _make_manager()
        result = await manager.complete_recovery()
        assert result is None

    async def test_persists_full_state(self) -> None:
        """complete_recovery persists FULL state to Redis."""
        snap = _make_snapshot(state=RecoveryState.SCALING_UP, current_multiplier=0.75)
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        await manager.complete_recovery()

        pipe = redis.pipeline.return_value
        pipe.hset.assert_called()


# ---------------------------------------------------------------------------
# RecoveryManager.clear
# ---------------------------------------------------------------------------


class TestClear:
    """RecoveryManager.clear removes Redis state."""

    async def test_calls_delete_on_redis(self) -> None:
        """clear() calls redis.delete on the correct key."""
        redis = _make_redis()
        manager = _make_manager(redis=redis, agent_id="abc-123")

        await manager.clear()

        redis.delete.assert_called_once_with("agent:recovery:abc-123")

    async def test_handles_redis_error_gracefully(self) -> None:
        """clear() does not raise when Redis.delete raises RedisError."""
        redis = _make_redis()
        redis.delete = AsyncMock(side_effect=RedisError("down"))
        manager = _make_manager(redis=redis)

        # Should not raise
        await manager.clear()


# ---------------------------------------------------------------------------
# Full recovery sequence integration
# ---------------------------------------------------------------------------


class TestFullRecoverySequence:
    """End-to-end walkthrough of the full recovery state machine."""

    async def test_full_4_day_sequence(self) -> None:
        """Simulate: start → ATR normalise → 4 qualifying days → FULL.

        Day 0: ATR elevated  → multiplier = 0.0
        Day 0: ATR normalises → multiplier = 0.25
        Day 1: advance_day (no loss) → multiplier = 0.25 → 0.50
        Day 2: advance_day (no loss) → multiplier = 0.50 → 0.75... wait, test
               advance_day(day=2) correctly.
        Day 3: advance_day → 0.75
        Day 4: advance_day + equity recovered → FULL (1.0)
        """
        # We control Redis state manually per step to simulate the sequence.
        redis = _make_redis()
        manager = _make_manager(redis=redis)

        # --- Start recovery ---
        redis.hgetall = AsyncMock(return_value={})
        snap = await manager.start_recovery(
            drawdown_pct=0.12,
            equity_at_trigger=Decimal("88000"),
            peak_equity=Decimal("100000"),
        )
        assert snap.state == RecoveryState.RECOVERING

        # --- ATR still elevated → 0.0 ---
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        mult = await manager.get_size_multiplier(
            current_atr=150.0,
            median_atr=80.0,
            current_equity=Decimal("88000"),
        )
        assert mult == 0.0

        # --- ATR normalises → transitions to SCALING_UP, returns 0.25 ---
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        mult = await manager.get_size_multiplier(
            current_atr=100.0,
            median_atr=80.0,
            current_equity=Decimal("88000"),
        )
        assert mult == pytest.approx(0.25)

        # Update our local snap to match what was persisted
        scaling_snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=0,
            current_multiplier=0.25,
            peak_equity="100000",
            equity_at_trigger="88000",
        )

        # --- Day 1: advance (no loss), equity at 89000 (below target 94000) ---
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(scaling_snap))
        snap1 = await manager.advance_day(current_equity=Decimal("89000"), had_loss=False)
        assert snap1 is not None
        assert snap1.days_scaling == 1
        assert snap1.current_multiplier == pytest.approx(0.25)

        # --- Day 2 ---
        day1_snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=1,
            current_multiplier=0.25,
            peak_equity="100000",
            equity_at_trigger="88000",
        )
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(day1_snap))
        snap2 = await manager.advance_day(current_equity=Decimal("90000"), had_loss=False)
        assert snap2 is not None
        assert snap2.current_multiplier == pytest.approx(0.50)

        # --- Day 3 ---
        day2_snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=2,
            current_multiplier=0.50,
            peak_equity="100000",
            equity_at_trigger="88000",
        )
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(day2_snap))
        snap3 = await manager.advance_day(current_equity=Decimal("92000"), had_loss=False)
        assert snap3 is not None
        assert snap3.current_multiplier == pytest.approx(0.75)

        # --- Day 4: equity has recovered to 95000 (>= target 94000) → FULL ---
        day3_snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=3,
            current_multiplier=0.75,
            peak_equity="100000",
            equity_at_trigger="88000",
        )
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(day3_snap))
        snap4 = await manager.advance_day(current_equity=Decimal("95000"), had_loss=False)
        assert snap4 is not None
        assert snap4.state == RecoveryState.FULL
        assert snap4.current_multiplier == pytest.approx(1.0)

    async def test_loss_day_delays_recovery(self) -> None:
        """A loss day in SCALING_UP pauses the ramp for one day."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=1,
            current_multiplier=0.25,
            peak_equity="100000",
            equity_at_trigger="88000",
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        # Loss day — no progress
        result = await manager.advance_day(
            current_equity=Decimal("87000"),
            had_loss=True,
        )
        assert result is not None
        assert result.days_scaling == 1
        assert result.current_multiplier == pytest.approx(0.25)

    async def test_redis_save_failure_is_non_crashing(self) -> None:
        """A Redis write failure during advance_day is logged but does not raise."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=0,
            current_multiplier=0.25,
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        # Make pipeline.execute raise on the advance_day save call
        pipe = redis.pipeline.return_value
        pipe.execute = AsyncMock(side_effect=RedisError("write error"))
        manager = _make_manager(redis=redis)

        # Should not raise despite Redis failure
        result = await manager.advance_day(
            current_equity=Decimal("90000"),
            had_loss=False,
        )
        # Result is still computed correctly even if persistence failed
        assert result is not None

    async def test_equity_gate_prevents_premature_full(self) -> None:
        """Even on day 4, FULL is not reached if equity target is not met."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=3,
            current_multiplier=0.75,
            peak_equity="100000",
            equity_at_trigger="88000",
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        # target = 94000; equity = 91000 < 94000 → not FULL
        result = await manager.advance_day(
            current_equity=Decimal("91000"),
            had_loss=False,
        )
        assert result is not None
        assert result.state == RecoveryState.SCALING_UP
        assert result.current_multiplier == pytest.approx(0.75)

    async def test_complete_recovery_bypasses_equity_wait(self) -> None:
        """complete_recovery immediately goes FULL regardless of equity level."""
        snap = _make_snapshot(
            state=RecoveryState.SCALING_UP,
            days_scaling=2,
            current_multiplier=0.50,
            peak_equity="100000",
            equity_at_trigger="88000",
        )
        redis = _make_redis()
        redis.hgetall = AsyncMock(return_value=_snapshot_as_redis_bytes(snap))
        manager = _make_manager(redis=redis)

        result = await manager.complete_recovery()
        assert result is not None
        assert result.state == RecoveryState.FULL
        assert result.current_multiplier == 1.0
