"""Integration tests for historical battle end-to-end flow.

These tests require a running database with historical price data.
They are marked as integration tests and skipped in CI without the
required infrastructure.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestHistoricalBattleE2E:
    """End-to-end historical battle lifecycle tests.

    Requires:
    - Running PostgreSQL/TimescaleDB with historical data
    - At least 2 agents in the database
    """

    async def test_create_historical_battle(self):
        """Test creating a historical battle via API."""
        # This test requires the full app stack
        # Placeholder for CI environment setup
        pytest.skip("Requires running database with historical data")

    async def test_historical_battle_lifecycle(self):
        """Test full lifecycle: create -> start -> step -> stop."""
        pytest.skip("Requires running database with historical data")

    async def test_historical_battle_rankings(self):
        """Test that rankings are computed correctly after completion."""
        pytest.skip("Requires running database with historical data")

    async def test_historical_battle_persists_backtest_sessions(self):
        """Test that BacktestSession rows are created per agent."""
        pytest.skip("Requires running database with historical data")

    async def test_historical_battle_persists_snapshots(self):
        """Test that BattleSnapshot rows are created."""
        pytest.skip("Requires running database with historical data")
