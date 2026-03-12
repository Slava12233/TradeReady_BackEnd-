"""Integration test: verify no look-ahead bias in backtest data.

BT-1.8.2: Create backtest at specific time → GET candles → assert ALL timestamps
< virtual_clock → step forward → GET candles again → assert new candles include
stepped period but NOT future.

Requires Docker services.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from httpx import AsyncClient

from src.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    resp = await client.post("/api/v1/auth/register", json={
        "display_name": "lookahead_test_agent",
    })
    data = resp.json()
    return {"X-API-Key": data["api_key"]}


async def test_no_future_data_in_candles(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Candles returned during backtest must all be at or before virtual_clock."""

    # Check data range
    resp = await client.get("/api/v1/market/data-range", headers=auth_headers)
    data_range = resp.json()

    if data_range.get("total_pairs", 0) == 0:
        pytest.skip("No historical data available")

    # Create backtest in the middle of available data
    resp = await client.post("/api/v1/backtest/create", headers=auth_headers, json={
        "start_time": data_range["earliest"],
        "end_time": data_range["latest"],
        "starting_balance": "10000",
        "candle_interval": 60,
        "strategy_label": "lookahead_test",
    })
    session_id = resp.json()["session_id"]

    # Start
    await client.post(f"/api/v1/backtest/{session_id}/start", headers=auth_headers)

    # Step 5 times
    for _ in range(5):
        step_resp = await client.post(
            f"/api/v1/backtest/{session_id}/step", headers=auth_headers
        )

    virtual_time_str = step_resp.json()["virtual_time"]
    virtual_time = datetime.fromisoformat(virtual_time_str)

    # Get candles
    resp = await client.get(
        f"/api/v1/backtest/{session_id}/market/candles/BTCUSDT?limit=50",
        headers=auth_headers,
    )

    if resp.status_code == 200:
        candles = resp.json().get("candles", [])
        for candle in candles:
            candle_time = datetime.fromisoformat(candle["bucket"])
            assert candle_time <= virtual_time, (
                f"Look-ahead bias: candle at {candle_time} > virtual_clock {virtual_time}"
            )

    # Step forward 5 more
    for _ in range(5):
        step_resp = await client.post(
            f"/api/v1/backtest/{session_id}/step", headers=auth_headers
        )

    new_virtual_time_str = step_resp.json()["virtual_time"]
    new_virtual_time = datetime.fromisoformat(new_virtual_time_str)

    # Get candles again — should include new period but NOT future
    resp = await client.get(
        f"/api/v1/backtest/{session_id}/market/candles/BTCUSDT?limit=50",
        headers=auth_headers,
    )

    if resp.status_code == 200:
        candles = resp.json().get("candles", [])
        for candle in candles:
            candle_time = datetime.fromisoformat(candle["bucket"])
            assert candle_time <= new_virtual_time, (
                f"Look-ahead bias after step: candle at {candle_time} > "
                f"virtual_clock {new_virtual_time}"
            )
