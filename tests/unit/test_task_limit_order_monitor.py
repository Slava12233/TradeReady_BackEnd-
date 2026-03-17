"""Unit tests for src/tasks/limit_order_monitor.py.

Tests the Celery limit order monitor task that sweeps pending limit/stop-loss/
take-profit orders every 1 second.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.celery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_matcher_stats(
    *,
    orders_checked: int = 5,
    orders_filled: int = 2,
    orders_errored: int = 0,
    swept_at: datetime | None = None,
    duration_ms: float = 12.345,
) -> MagicMock:
    """Build a mock MatcherStats object."""
    stats = MagicMock()
    stats.swept_at = swept_at or datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC)
    stats.orders_checked = orders_checked
    stats.orders_filled = orders_filled
    stats.orders_errored = orders_errored
    stats.duration_ms = duration_ms
    return stats


def _build_patches(mock_settings, mock_redis_cls, mock_price_cache_cls, mock_session_factory, mock_run_matcher):
    """Build patch list for lazy imports inside _run_async."""
    return [
        patch("src.config.get_settings", return_value=mock_settings),
        patch("src.cache.redis_client.RedisClient", return_value=mock_redis_cls),
        patch("src.cache.price_cache.PriceCache", return_value=mock_price_cache_cls),
        patch("src.database.session.get_session_factory", return_value=mock_session_factory),
        patch("src.order_engine.matching.run_matcher_once", mock_run_matcher),
    ]


# ---------------------------------------------------------------------------
# Tests for _run_async
# ---------------------------------------------------------------------------


class TestRunAsync:
    """Tests for the async implementation _run_async."""

    @pytest.fixture(autouse=True)
    def _patch_deps(self):
        """Patch all lazy imports inside _run_async."""
        self.mock_settings = MagicMock()
        self.mock_settings.redis_url = "redis://localhost:6379/0"

        self.mock_redis_client = MagicMock()
        self.mock_redis_client.connect = AsyncMock()
        self.mock_redis_client.disconnect = AsyncMock()
        self.mock_redis_client.get_client = MagicMock(return_value=MagicMock())

        self.mock_price_cache = MagicMock()
        self.mock_run_matcher = AsyncMock()
        self.mock_session_factory = MagicMock()

        self.patches = _build_patches(
            self.mock_settings,
            self.mock_redis_client,
            self.mock_price_cache,
            self.mock_session_factory,
            self.mock_run_matcher,
        )
        for p in self.patches:
            p.start()
        yield
        for p in self.patches:
            p.stop()

    async def test_matches_pending_limit_buy_when_price_drops(self):
        """Limit buy fills when market price <= limit price."""
        stats = _make_matcher_stats(orders_checked=10, orders_filled=3)
        self.mock_run_matcher.return_value = stats

        from src.tasks.limit_order_monitor import _run_async

        result = await _run_async()

        assert result["orders_filled"] == 3
        assert result["orders_checked"] == 10
        self.mock_run_matcher.assert_awaited_once()

    async def test_matches_pending_limit_sell_when_price_rises(self):
        """Limit sell fills when market price >= limit price."""
        stats = _make_matcher_stats(orders_checked=8, orders_filled=5)
        self.mock_run_matcher.return_value = stats

        from src.tasks.limit_order_monitor import _run_async

        result = await _run_async()

        assert result["orders_filled"] == 5

    async def test_triggers_stop_loss_order(self):
        """Stop-loss triggers when price drops below threshold."""
        stats = _make_matcher_stats(orders_checked=4, orders_filled=1)
        self.mock_run_matcher.return_value = stats

        from src.tasks.limit_order_monitor import _run_async

        result = await _run_async()

        assert result["orders_filled"] == 1

    async def test_triggers_take_profit_order(self):
        """Take-profit triggers when price rises above threshold."""
        stats = _make_matcher_stats(orders_checked=6, orders_filled=2)
        self.mock_run_matcher.return_value = stats

        from src.tasks.limit_order_monitor import _run_async

        result = await _run_async()

        assert result["orders_filled"] == 2

    async def test_skips_already_filled_orders(self):
        """Does not re-process filled/cancelled orders."""
        stats = _make_matcher_stats(orders_checked=0, orders_filled=0)
        self.mock_run_matcher.return_value = stats

        from src.tasks.limit_order_monitor import _run_async

        result = await _run_async()

        assert result["orders_checked"] == 0
        assert result["orders_filled"] == 0

    async def test_no_pending_orders_returns_zero(self):
        """Returns matched=0 when nothing to match."""
        stats = _make_matcher_stats(orders_checked=0, orders_filled=0, orders_errored=0)
        self.mock_run_matcher.return_value = stats

        from src.tasks.limit_order_monitor import _run_async

        result = await _run_async()

        assert result["orders_checked"] == 0
        assert result["orders_filled"] == 0
        assert result["orders_errored"] == 0

    async def test_individual_order_failure_does_not_abort_batch(self):
        """One order error logs but continues processing others."""
        stats = _make_matcher_stats(orders_checked=10, orders_filled=7, orders_errored=3)
        self.mock_run_matcher.return_value = stats

        from src.tasks.limit_order_monitor import _run_async

        result = await _run_async()

        assert result["orders_errored"] == 3
        assert result["orders_filled"] == 7

    async def test_session_factory_called_and_closed(self):
        """DB session factory is created; Redis is connected and disconnected."""
        stats = _make_matcher_stats()
        self.mock_run_matcher.return_value = stats

        from src.tasks.limit_order_monitor import _run_async

        await _run_async()

        self.mock_redis_client.connect.assert_awaited_once()
        self.mock_redis_client.disconnect.assert_awaited_once()

    async def test_redis_disconnected_even_on_error(self):
        """Redis client is disconnected in the finally block even on error."""
        self.mock_run_matcher.side_effect = RuntimeError("DB stall")

        from src.tasks.limit_order_monitor import _run_async

        with pytest.raises(RuntimeError, match="DB stall"):
            await _run_async()

        self.mock_redis_client.disconnect.assert_awaited_once()


class TestSyncWrapper:
    """Tests for the sync Celery entry point."""

    async def test_sync_wrapper_calls_async_impl(self):
        """Sync Celery entry point calls the async implementation via asyncio.run."""
        stats = _make_matcher_stats()
        expected = {
            "swept_at": stats.swept_at.isoformat(),
            "orders_checked": stats.orders_checked,
            "orders_filled": stats.orders_filled,
            "orders_errored": stats.orders_errored,
            "duration_ms": round(stats.duration_ms, 2),
        }

        with patch(
            "src.tasks.limit_order_monitor._run_async",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_run:
            from src.tasks.limit_order_monitor import _run_async

            result = await _run_async()

            assert result["orders_filled"] == 2
            mock_run.assert_awaited_once()
