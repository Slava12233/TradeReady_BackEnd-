"""Unit tests for src/tasks/candle_aggregation.py.

Tests the Celery task that refreshes TimescaleDB continuous aggregate views.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.celery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session_factory():
    """Build a mock async session factory."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    mock_factory = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory.return_value = mock_ctx

    return mock_factory, mock_session


# ---------------------------------------------------------------------------
# Tests for _run_refresh
# ---------------------------------------------------------------------------


class TestRefreshCandleAggregates:
    """Tests for the candle aggregate refresh task."""

    async def test_refreshes_materialized_views(self):
        """Calls REFRESH on all 4 OHLCV views."""
        mock_factory, mock_session = _mock_session_factory()

        with (
            patch("src.config.get_settings", return_value=MagicMock()),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
        ):
            from src.tasks.candle_aggregation import _run_refresh

            result = await _run_refresh()

        assert result["views_refreshed"] == 4
        assert result["views_failed"] == 0
        assert len(result["view_details"]) == 4
        for detail in result["view_details"]:
            assert detail["status"] == "ok"

    async def test_handles_empty_tick_data(self):
        """No ticks = no error, views still refreshed."""
        mock_factory, mock_session = _mock_session_factory()

        with (
            patch("src.config.get_settings", return_value=MagicMock()),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
        ):
            from src.tasks.candle_aggregation import _run_refresh

            result = await _run_refresh()

        assert result["views_refreshed"] == 4
        assert "duration_ms" in result

    async def test_returns_success_status(self):
        """Return dict confirms completion with view_details."""
        mock_factory, mock_session = _mock_session_factory()

        with (
            patch("src.config.get_settings", return_value=MagicMock()),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
        ):
            from src.tasks.candle_aggregation import _run_refresh

            result = await _run_refresh()

        assert "views_refreshed" in result
        assert "views_failed" in result
        assert "view_details" in result
        assert "duration_ms" in result

    async def test_individual_view_failure_isolated(self):
        """Error in one view does not abort remaining views."""
        view_calls = []

        async def _mock_refresh_view(session, view_name, start_offset, end_offset):
            view_calls.append(view_name)
            if view_name == "candles_5m":
                raise RuntimeError("candles_5m refresh failed")

        # Per-call session factory since each view uses its own session
        def _factory():
            mock_session = AsyncMock()
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            return mock_ctx

        mock_factory = MagicMock(side_effect=_factory)

        with (
            patch("src.config.get_settings", return_value=MagicMock()),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.tasks.candle_aggregation._refresh_view", side_effect=_mock_refresh_view),
        ):
            from src.tasks.candle_aggregation import _run_refresh

            result = await _run_refresh()

        assert result["views_refreshed"] == 3
        assert result["views_failed"] == 1
        assert len(view_calls) == 4  # All 4 views attempted

    async def test_view_details_contain_expected_views(self):
        """View details list includes all 4 candle views."""
        mock_factory, mock_session = _mock_session_factory()

        with (
            patch("src.config.get_settings", return_value=MagicMock()),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
        ):
            from src.tasks.candle_aggregation import _run_refresh

            result = await _run_refresh()

        view_names = [d["view"] for d in result["view_details"]]
        assert view_names == ["candles_1m", "candles_5m", "candles_1h", "candles_1d"]
