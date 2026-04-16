"""Integration test: agent-scoped backtest lifecycle.

Creates 2 agents under the same account, runs a backtest for each,
and verifies isolation: agent A's list shows only its backtest,
account-level list shows both.

Requires Docker services.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient
import pytest

from src.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def account_and_agents(client: AsyncClient) -> dict:
    """Register an account and create two agents, returning auth info."""
    # Register account (creates first agent automatically)
    resp = await client.post(
        "/api/v1/auth/register",
        json={"display_name": "scoped_backtest_test"},
    )
    data = resp.json()
    jwt_token = data.get("token") or data.get("jwt_token")
    jwt_headers = {"Authorization": f"Bearer {jwt_token}"} if jwt_token else {"X-API-Key": data["api_key"]}

    # Create agent A
    resp_a = await client.post(
        "/api/v1/agents",
        headers=jwt_headers,
        json={"display_name": "Agent A", "starting_balance": "10000"},
    )
    agent_a = resp_a.json()

    # Create agent B
    resp_b = await client.post(
        "/api/v1/agents",
        headers=jwt_headers,
        json={"display_name": "Agent B", "starting_balance": "10000"},
    )
    agent_b = resp_b.json()

    return {
        "jwt_headers": jwt_headers,
        "agent_a_id": agent_a["id"],
        "agent_a_key": agent_a.get("api_key"),
        "agent_b_id": agent_b["id"],
        "agent_b_key": agent_b.get("api_key"),
    }


async def test_agent_scoped_backtest_isolation(client: AsyncClient, account_and_agents: dict) -> None:
    """Each agent's backtest list only shows its own sessions; account list shows all."""
    info = account_and_agents
    jwt_headers = info["jwt_headers"]

    # Check data availability
    resp = await client.get("/api/v1/market/data-range", headers=jwt_headers)
    data_range = resp.json()
    if data_range.get("total_pairs", 0) == 0:
        pytest.skip("No historical data available")

    earliest = data_range["earliest"]
    latest = data_range["latest"]

    # Create backtest for Agent A
    resp_a = await client.post(
        "/api/v1/backtest/create",
        headers={**jwt_headers, "X-Agent-Id": info["agent_a_id"]},
        json={
            "start_time": earliest,
            "end_time": latest,
            "starting_balance": "10000",
            "strategy_label": "agent_a_strategy",
            "agent_id": info["agent_a_id"],
        },
    )
    assert resp_a.status_code == 200
    session_a = resp_a.json()
    assert session_a["agent_id"] == info["agent_a_id"]

    # Create backtest for Agent B
    resp_b = await client.post(
        "/api/v1/backtest/create",
        headers={**jwt_headers, "X-Agent-Id": info["agent_b_id"]},
        json={
            "start_time": earliest,
            "end_time": latest,
            "starting_balance": "10000",
            "strategy_label": "agent_b_strategy",
            "agent_id": info["agent_b_id"],
        },
    )
    assert resp_b.status_code == 200
    session_b = resp_b.json()
    assert session_b["agent_id"] == info["agent_b_id"]

    # List all backtests (no agent filter) — should see both
    resp_all = await client.get(
        "/api/v1/backtest/list",
        headers=jwt_headers,
    )
    assert resp_all.status_code == 200
    all_backtests = resp_all.json()["backtests"]
    all_ids = {bt["session_id"] for bt in all_backtests}
    assert session_a["session_id"] in all_ids
    assert session_b["session_id"] in all_ids

    # List backtests for Agent A only
    resp_a_list = await client.get(
        f"/api/v1/backtest/list?agent_id={info['agent_a_id']}",
        headers=jwt_headers,
    )
    assert resp_a_list.status_code == 200
    a_backtests = resp_a_list.json()["backtests"]
    a_ids = {bt["session_id"] for bt in a_backtests}
    assert session_a["session_id"] in a_ids
    assert session_b["session_id"] not in a_ids

    # List backtests for Agent B only
    resp_b_list = await client.get(
        f"/api/v1/backtest/list?agent_id={info['agent_b_id']}",
        headers=jwt_headers,
    )
    assert resp_b_list.status_code == 200
    b_backtests = resp_b_list.json()["backtests"]
    b_ids = {bt["session_id"] for bt in b_backtests}
    assert session_b["session_id"] in b_ids
    assert session_a["session_id"] not in b_ids

    # Verify agent_id appears in status response
    resp_status = await client.get(
        f"/api/v1/backtest/{session_a['session_id']}/status",
        headers=jwt_headers,
    )
    assert resp_status.status_code == 200
    status_data = resp_status.json()
    assert status_data["agent_id"] == info["agent_a_id"]
