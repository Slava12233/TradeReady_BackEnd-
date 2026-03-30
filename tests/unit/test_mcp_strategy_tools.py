"""Unit tests for MCP strategy management, strategy testing, and training tools.

Tests cover the 15 new tools added in STR-4.4:

Strategy Management (7):
- create_strategy, get_strategies, get_strategy, create_strategy_version,
  get_strategy_versions, deploy_strategy, undeploy_strategy

Strategy Testing (5):
- run_strategy_test, get_test_status, get_test_results, compare_versions,
  get_strategy_recommendations

Training Observation (3):
- get_training_runs, get_training_run_detail, compare_training_runs

Each test verifies:
1. Correct HTTP method
2. Correct endpoint path
3. Correct parameters/body
4. Response formatted as JSON TextContent
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

mcp = pytest.importorskip("mcp", reason="mcp package not installed")
import mcp.types as types  # noqa: E402
from src.mcp.tools import _dispatch  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers (same pattern as test_mcp_tools.py)
# ---------------------------------------------------------------------------

_DUMMY_REQUEST = httpx.Request("GET", "http://localhost:8000/api/v1/test")


def _make_response(
    status_code: int = 200,
    body: Any = None,
) -> httpx.Response:
    """Build a minimal ``httpx.Response`` for mocking purposes."""
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body or {}).encode(),
        headers={"content-type": "application/json"},
        request=_DUMMY_REQUEST,
    )


async def _run_dispatch(
    name: str,
    args: dict[str, Any],
    mock_data: Any = None,
    *,
    status_code: int = 200,
) -> list[types.TextContent]:
    """Helper: run _dispatch with a mocked HTTP client returning *mock_data*."""
    client = AsyncMock(spec=httpx.AsyncClient)
    response = _make_response(status_code, mock_data)
    client.request = AsyncMock(return_value=response)
    return await _dispatch(name, args, client)


# ---------------------------------------------------------------------------
# Strategy Management tools (7 tests)
# ---------------------------------------------------------------------------


class TestDispatchStrategyManagement:
    """Tests for strategy management tools."""

    @pytest.mark.asyncio
    async def test_create_strategy_posts_with_name_and_definition(self) -> None:
        definition = {"pairs": ["BTCUSDT"], "timeframe": "1h", "entry_conditions": []}
        mock_data = {"id": "strat-1", "name": "Momentum", "status": "draft", "version": 1}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch(
            "create_strategy",
            {"name": "Momentum", "definition": definition},
            client,
        )

        call_args = client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/v1/strategies"
        body = call_args[1]["json"]
        assert body["name"] == "Momentum"
        assert body["definition"] == definition
        assert "description" not in body

        parsed = json.loads(result[0].text)
        assert parsed["id"] == "strat-1"
        assert parsed["status"] == "draft"

    @pytest.mark.asyncio
    async def test_create_strategy_includes_optional_description(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {"id": "strat-2"}))

        await _dispatch(
            "create_strategy",
            {"name": "Mean Rev", "definition": {}, "description": "Mean reversion strat"},
            client,
        )

        body = client.request.call_args[1]["json"]
        assert body["description"] == "Mean reversion strat"

    @pytest.mark.asyncio
    async def test_get_strategies_calls_correct_endpoint(self) -> None:
        mock_data = [{"id": "strat-1", "name": "Momentum", "status": "draft"}]
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch("get_strategies", {}, client)

        call_args = client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/api/v1/strategies"
        parsed = json.loads(result[0].text)
        assert isinstance(parsed, list)

    @pytest.mark.asyncio
    async def test_get_strategies_passes_optional_filters(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, []))

        await _dispatch(
            "get_strategies",
            {"status": "deployed", "limit": 10, "offset": 5},
            client,
        )

        params = client.request.call_args[1]["params"]
        assert params["status"] == "deployed"
        assert params["limit"] == 10
        assert params["offset"] == 5

    @pytest.mark.asyncio
    async def test_get_strategy_fetches_by_id(self) -> None:
        mock_data = {"id": "strat-abc", "name": "Alpha", "version": 3, "status": "validated"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch("get_strategy", {"strategy_id": "strat-abc"}, client)

        call_args = client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/api/v1/strategies/strat-abc"
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "strat-abc"
        assert parsed["version"] == 3

    @pytest.mark.asyncio
    async def test_create_strategy_version_posts_definition(self) -> None:
        new_def = {"pairs": ["ETHUSDT"], "timeframe": "4h"}
        mock_data = {"id": "strat-abc", "version": 2}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch(
            "create_strategy_version",
            {"strategy_id": "strat-abc", "definition": new_def, "change_notes": "Added ETH"},
            client,
        )

        call_args = client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/v1/strategies/strat-abc/versions"
        body = call_args[1]["json"]
        assert body["definition"] == new_def
        assert body["change_notes"] == "Added ETH"
        parsed = json.loads(result[0].text)
        assert parsed["version"] == 2

    @pytest.mark.asyncio
    async def test_create_strategy_version_omits_change_notes_when_absent(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch(
            "create_strategy_version",
            {"strategy_id": "strat-abc", "definition": {"pairs": ["BTCUSDT"]}},
            client,
        )

        body = client.request.call_args[1]["json"]
        assert "change_notes" not in body

    @pytest.mark.asyncio
    async def test_get_strategy_versions_calls_correct_endpoint(self) -> None:
        mock_data = [{"version": 1}, {"version": 2}]
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch("get_strategy_versions", {"strategy_id": "strat-xyz"}, client)

        call_args = client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/api/v1/strategies/strat-xyz/versions"
        parsed = json.loads(result[0].text)
        assert len(parsed) == 2

    @pytest.mark.asyncio
    async def test_deploy_strategy_posts_with_version(self) -> None:
        mock_data = {"id": "strat-abc", "status": "deployed", "deployed_version": 2}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch(
            "deploy_strategy",
            {"strategy_id": "strat-abc", "version": 2},
            client,
        )

        call_args = client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/v1/strategies/strat-abc/deploy"
        body = call_args[1]["json"]
        assert body["version"] == 2
        parsed = json.loads(result[0].text)
        assert parsed["status"] == "deployed"

    @pytest.mark.asyncio
    async def test_undeploy_strategy_posts_to_correct_endpoint(self) -> None:
        mock_data = {"id": "strat-abc", "status": "validated"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch("undeploy_strategy", {"strategy_id": "strat-abc"}, client)

        call_args = client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/v1/strategies/strat-abc/undeploy"
        parsed = json.loads(result[0].text)
        assert parsed["status"] == "validated"


# ---------------------------------------------------------------------------
# Strategy Testing tools (5 tests)
# ---------------------------------------------------------------------------


class TestDispatchStrategyTesting:
    """Tests for strategy testing tools."""

    @pytest.mark.asyncio
    async def test_run_strategy_test_posts_with_required_args(self) -> None:
        mock_data = {"test_id": "test-001", "status": "running", "episodes_total": 10}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch(
            "run_strategy_test",
            {"strategy_id": "strat-abc", "version": 3},
            client,
        )

        call_args = client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/v1/strategies/strat-abc/test"
        body = call_args[1]["json"]
        assert body["version"] == 3
        parsed = json.loads(result[0].text)
        assert parsed["test_id"] == "test-001"

    @pytest.mark.asyncio
    async def test_run_strategy_test_includes_optional_params(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {"test_id": "test-002"}))

        date_range = {"start": "2025-01-01", "end": "2025-06-01"}
        await _dispatch(
            "run_strategy_test",
            {
                "strategy_id": "strat-abc",
                "version": 1,
                "episodes": 20,
                "date_range": date_range,
                "episode_duration_days": 14,
            },
            client,
        )

        body = client.request.call_args[1]["json"]
        assert body["episodes"] == 20
        assert body["date_range"] == date_range
        assert body["episode_duration_days"] == 14

    @pytest.mark.asyncio
    async def test_get_test_status_fetches_by_ids(self) -> None:
        mock_data = {"test_id": "test-001", "status": "completed", "episodes_completed": 10}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch(
            "get_test_status",
            {"strategy_id": "strat-abc", "test_id": "test-001"},
            client,
        )

        call_args = client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/api/v1/strategies/strat-abc/tests/test-001"
        parsed = json.loads(result[0].text)
        assert parsed["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_test_results_fetches_by_ids(self) -> None:
        mock_data = {
            "test_id": "test-001",
            "aggregate_metrics": {"avg_roi": "5.2", "avg_sharpe": "1.1"},
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch(
            "get_test_results",
            {"strategy_id": "strat-abc", "test_id": "test-001"},
            client,
        )

        call_args = client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/api/v1/strategies/strat-abc/tests/test-001"
        parsed = json.loads(result[0].text)
        assert "aggregate_metrics" in parsed

    @pytest.mark.asyncio
    async def test_compare_versions_passes_version_params(self) -> None:
        mock_data = {"v1_metrics": {"roi": "3.2"}, "v2_metrics": {"roi": "5.8"}, "deltas": {"roi": "+2.6"}}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch(
            "compare_versions",
            {"strategy_id": "strat-abc", "v1": 1, "v2": 2},
            client,
        )

        call_args = client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/api/v1/strategies/strat-abc/compare-versions"
        params = call_args[1]["params"]
        assert params["v1"] == 1
        assert params["v2"] == 2
        parsed = json.loads(result[0].text)
        assert "deltas" in parsed

    @pytest.mark.asyncio
    async def test_get_strategy_recommendations_extracts_recommendations(self) -> None:
        mock_data = {
            "recommendations": [
                {"rule": "low_sharpe", "message": "Sharpe ratio below 1.0"},
                {"rule": "high_drawdown", "message": "Max drawdown exceeds 20%"},
            ],
            "other_data": "ignored",
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch(
            "get_strategy_recommendations",
            {"strategy_id": "strat-abc"},
            client,
        )

        call_args = client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/api/v1/strategies/strat-abc/test-results"
        parsed = json.loads(result[0].text)
        assert parsed["strategy_id"] == "strat-abc"
        assert len(parsed["recommendations"]) == 2
        assert parsed["recommendations"][0]["rule"] == "low_sharpe"

    @pytest.mark.asyncio
    async def test_get_strategy_recommendations_empty_when_no_recommendations(self) -> None:
        mock_data = {"some_field": "value"}
        result = await _run_dispatch("get_strategy_recommendations", {"strategy_id": "strat-abc"}, mock_data)

        parsed = json.loads(result[0].text)
        assert parsed["recommendations"] == []


# ---------------------------------------------------------------------------
# Training Observation tools (3 tests)
# ---------------------------------------------------------------------------


class TestDispatchTrainingObservation:
    """Tests for training observation tools."""

    @pytest.mark.asyncio
    async def test_get_training_runs_calls_correct_endpoint(self) -> None:
        mock_data = [{"run_id": "run-1", "status": "completed"}]
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch("get_training_runs", {}, client)

        call_args = client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/api/v1/training/runs"
        parsed = json.loads(result[0].text)
        assert isinstance(parsed, list)

    @pytest.mark.asyncio
    async def test_get_training_runs_passes_optional_filters(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, []))

        await _dispatch(
            "get_training_runs",
            {"status": "running", "limit": 25, "offset": 10},
            client,
        )

        params = client.request.call_args[1]["params"]
        assert params["status"] == "running"
        assert params["limit"] == 25
        assert params["offset"] == 10

    @pytest.mark.asyncio
    async def test_get_training_run_detail_fetches_by_run_id(self) -> None:
        mock_data = {
            "run_id": "run-abc",
            "status": "completed",
            "learning_curve": [{"episode": 1, "reward": 0.5}],
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch("get_training_run_detail", {"run_id": "run-abc"}, client)

        call_args = client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/api/v1/training/runs/run-abc"
        parsed = json.loads(result[0].text)
        assert parsed["run_id"] == "run-abc"
        assert "learning_curve" in parsed

    @pytest.mark.asyncio
    async def test_compare_training_runs_passes_run_ids(self) -> None:
        run_id_1 = "550e8400-e29b-41d4-a716-446655440001"
        run_id_2 = "550e8400-e29b-41d4-a716-446655440002"
        run_ids_str = f"{run_id_1},{run_id_2}"
        mock_data = {
            "runs": [
                {"run_id": run_id_1, "avg_roi": "3.5"},
                {"run_id": run_id_2, "avg_roi": "5.1"},
            ]
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, mock_data))

        result = await _dispatch(
            "compare_training_runs",
            {"run_ids": run_ids_str},
            client,
        )

        call_args = client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/api/v1/training/compare"
        params = call_args[1]["params"]
        assert params["run_ids"] == run_ids_str
        parsed = json.loads(result[0].text)
        assert len(parsed["runs"]) == 2
