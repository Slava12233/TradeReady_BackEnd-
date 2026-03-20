"""Tests for agent/strategies/evolutionary/battle_runner.py :: BattleRunner.

All HTTP calls are mocked with unittest.mock — no running platform is required.

Covers:
- BattleRunner creation with pre-supplied JWT (skips login)
- setup_agents: correct POST to /api/v1/agents, agent IDs stored
- assign_strategies: sends strategy definition JSONB to REST client
- get_fitness: computes sharpe - 0.5 * drawdown correctly
- get_fitness: API failure handling assigns FAILURE_FITNESS (-999)
- Error propagation (HTTP errors, missing keys)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent.config import AgentConfig
from agent.strategies.evolutionary.battle_runner import FAILURE_FITNESS, BattleRunner
from agent.strategies.evolutionary.genome import StrategyGenome
from agent.tools.rest_tools import PlatformRESTClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    """Build a minimal valid AgentConfig without reading a .env file."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_testkey")
    monkeypatch.setenv("PLATFORM_API_SECRET", "sk_live_testsecret")
    monkeypatch.setenv("PLATFORM_BASE_URL", "http://testserver")
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _mock_rest_client() -> MagicMock:
    """Build a mock PlatformRESTClient with AsyncMock methods."""
    client = MagicMock(spec=PlatformRESTClient)
    client.create_strategy = AsyncMock(return_value={"strategy_id": "strat-001"})
    client.create_version = AsyncMock(return_value={"version": 2})
    return client


def _ok_response(json_data: dict[str, Any]) -> MagicMock:
    """Build a 200-OK mock httpx.Response returning the given JSON."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.text = str(json_data)
    resp.raise_for_status.return_value = None
    return resp


def _error_response(status: int, message: str = "error") -> MagicMock:
    """Build a mock httpx.Response that raises HTTPStatusError on raise_for_status."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = message
    resp.json.return_value = {"error": message}
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        message=f"HTTP {status}",
        request=MagicMock(),
        response=resp,
    )
    return resp


def _build_runner(
    config: AgentConfig,
    rest_client: MagicMock,
    jwt_client: MagicMock,
    jwt_token: str = "test-jwt-token",
) -> BattleRunner:
    """Construct a BattleRunner with a patched internal JWT client."""
    runner = BattleRunner(config, rest_client, jwt_token)
    runner._jwt_client = jwt_client
    return runner


def _make_genome(seed: int = 0) -> StrategyGenome:
    """Convenience factory for a deterministic genome."""
    return StrategyGenome.from_random(seed=seed)


def _make_agent_post_mock(agent_ids: list[str]) -> AsyncMock:
    """Return an AsyncMock for jwt_client.post that yields sequential agent IDs."""
    responses = [_ok_response({"agent_id": aid}) for aid in agent_ids]
    return AsyncMock(side_effect=responses)


# ---------------------------------------------------------------------------
# TestBattleRunnerCreation
# ---------------------------------------------------------------------------


class TestBattleRunnerCreation:
    """Tests for BattleRunner.__init__ and BattleRunner.create()."""

    def test_direct_construction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BattleRunner can be constructed directly with a pre-supplied JWT."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        runner = BattleRunner(config, rest, "my-jwt-token")
        assert runner._jwt_token == "my-jwt-token"
        assert runner.generation == 0
        assert runner.agent_ids == []

    async def test_create_with_provided_jwt_skips_login(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BattleRunner.create() with jwt_token skips the login request."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        with patch.object(BattleRunner, "_acquire_jwt", new_callable=AsyncMock) as mock_acquire:
            runner = await BattleRunner.create(config, rest, jwt_token="pre-supplied-jwt")
        mock_acquire.assert_not_called()
        assert runner._jwt_token == "pre-supplied-jwt"

    async def test_create_without_jwt_calls_acquire(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BattleRunner.create() without jwt_token calls _acquire_jwt once."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        with patch.object(
            BattleRunner,
            "_acquire_jwt",
            new_callable=AsyncMock,
            return_value="acquired-jwt",
        ) as mock_acquire:
            runner = await BattleRunner.create(config, rest, jwt_token=None)
        mock_acquire.assert_called_once_with(config)
        assert runner._jwt_token == "acquired-jwt"

    async def test_context_manager_closes_jwt_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Async context manager calls close() on exit."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        runner = BattleRunner(config, rest, "jwt")
        jwt_client = MagicMock()
        jwt_client.aclose = AsyncMock()
        runner._jwt_client = jwt_client
        async with runner:
            pass
        jwt_client.aclose.assert_called_once()

    async def test_acquire_jwt_raises_on_http_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_acquire_jwt raises RuntimeError when the login endpoint returns 4xx."""
        config = _make_config(monkeypatch)
        error_resp = _error_response(401, "Unauthorized")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                message="HTTP 401",
                request=MagicMock(),
                response=error_resp,
            )
        )
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            with pytest.raises(RuntimeError, match="JWT acquisition failed"):
                await BattleRunner._acquire_jwt(config)

    async def test_acquire_jwt_raises_on_missing_token_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_acquire_jwt raises RuntimeError when response lacks 'token' key."""
        config = _make_config(monkeypatch)
        ok_resp = _ok_response({"access_token": "wrong-key"})  # no 'token' key

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=ok_resp)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            with pytest.raises(RuntimeError, match="'token' key"):
                await BattleRunner._acquire_jwt(config)


# ---------------------------------------------------------------------------
# TestSetupAgents
# ---------------------------------------------------------------------------


class TestSetupAgents:
    """Tests for BattleRunner.setup_agents()."""

    async def test_setup_creates_correct_number_of_agents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """setup_agents(n) creates exactly n agents via POST /api/v1/agents."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        jwt_client = MagicMock()
        jwt_client.post = _make_agent_post_mock(["a-0", "a-1", "a-2"])
        runner = _build_runner(config, rest, jwt_client)

        agent_ids = await runner.setup_agents(population_size=3)

        assert len(agent_ids) == 3
        assert jwt_client.post.call_count == 3

    async def test_setup_stores_agent_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """setup_agents() stores the returned agent IDs in _agent_ids."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        jwt_client = MagicMock()
        jwt_client.post = _make_agent_post_mock(["uuid-0", "uuid-1"])
        runner = _build_runner(config, rest, jwt_client)

        await runner.setup_agents(population_size=2)

        assert runner.agent_ids == ["uuid-0", "uuid-1"]

    async def test_setup_posts_to_correct_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """setup_agents() posts to /api/v1/agents."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        jwt_client = MagicMock()
        jwt_client.post = _make_agent_post_mock(["some-id"])
        runner = _build_runner(config, rest, jwt_client)

        await runner.setup_agents(population_size=1)

        call_args = jwt_client.post.call_args
        assert call_args[0][0] == "/api/v1/agents"

    async def test_setup_agent_http_error_raises_runtime(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """setup_agents() raises RuntimeError when the API returns an HTTP error."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        jwt_client = MagicMock()
        err_resp = _error_response(500, "Server Error")
        jwt_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                message="HTTP 500",
                request=MagicMock(),
                response=err_resp,
            )
        )
        runner = _build_runner(config, rest, jwt_client)

        with pytest.raises(RuntimeError, match="Agent creation failed"):
            await runner.setup_agents(population_size=1)

    async def test_setup_agent_missing_agent_id_key_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """setup_agents() raises RuntimeError when response lacks 'agent_id'."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        jwt_client = MagicMock()
        jwt_client.post = AsyncMock(return_value=_ok_response({"id": "wrong-key"}))
        runner = _build_runner(config, rest, jwt_client)

        with pytest.raises(RuntimeError, match="agent_id"):
            await runner.setup_agents(population_size=1)

    async def test_setup_agent_names_follow_pattern(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Agents are named evo-gen0-agent0, evo-gen0-agent1, etc."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        jwt_client = MagicMock()
        jwt_client.post = _make_agent_post_mock(["id-1", "id-2", "id-3"])
        runner = _build_runner(config, rest, jwt_client)

        await runner.setup_agents(population_size=3)

        calls = jwt_client.post.call_args_list
        names = [c.kwargs["json"]["name"] for c in calls]
        assert names == ["evo-gen0-agent0", "evo-gen0-agent1", "evo-gen0-agent2"]


# ---------------------------------------------------------------------------
# TestAssignStrategies
# ---------------------------------------------------------------------------


class TestAssignStrategies:
    """Tests for BattleRunner.assign_strategies()."""

    def _setup_runner_with_agents(
        self, config: AgentConfig, agent_count: int
    ) -> tuple[BattleRunner, MagicMock, MagicMock]:
        """Build a runner with `agent_count` pre-populated agent IDs."""
        rest = _mock_rest_client()
        jwt_client = MagicMock()
        runner = _build_runner(config, rest, jwt_client)
        runner._agent_ids = [f"agent-{i}" for i in range(agent_count)]
        return runner, rest, jwt_client

    async def test_assign_calls_create_strategy_for_each_agent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """assign_strategies() calls create_strategy once per agent (first gen)."""
        config = _make_config(monkeypatch)
        runner, rest, _ = self._setup_runner_with_agents(config, 3)
        genomes = [_make_genome(i) for i in range(3)]

        await runner.assign_strategies(genomes)

        assert rest.create_strategy.call_count == 3

    async def test_assign_sends_correct_definition_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """assign_strategies() passes strategy definition with required JSONB keys."""
        config = _make_config(monkeypatch)
        runner, rest, _ = self._setup_runner_with_agents(config, 1)
        genome = _make_genome(seed=0)

        await runner.assign_strategies([genome])

        call_kwargs = rest.create_strategy.call_args.kwargs
        definition = call_kwargs["definition"]
        assert "pairs" in definition
        assert "entry_conditions" in definition
        assert "exit_conditions" in definition
        assert "position_size_pct" in definition
        assert "max_positions" in definition
        assert "filters" in definition
        assert definition["model_type"] == "rule_based"

    async def test_assign_count_mismatch_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """assign_strategies() raises ValueError when genome count != agent count."""
        config = _make_config(monkeypatch)
        runner, _, _ = self._setup_runner_with_agents(config, 3)
        genomes = [_make_genome(i) for i in range(2)]  # one too few

        with pytest.raises(ValueError, match="Genome count"):
            await runner.assign_strategies(genomes)

    async def test_second_generation_creates_version_not_strategy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Subsequent generations call create_version, not create_strategy."""
        config = _make_config(monkeypatch)
        runner, rest, _ = self._setup_runner_with_agents(config, 1)
        genomes = [_make_genome(0)]

        # First assignment: creates a strategy
        await runner.assign_strategies(genomes)
        assert rest.create_strategy.call_count == 1
        assert rest.create_version.call_count == 0

        # Second assignment (same agent, strategy already stored): creates version
        await runner.assign_strategies(genomes)
        assert rest.create_strategy.call_count == 1  # unchanged
        assert rest.create_version.call_count == 1

    async def test_assign_strategy_http_error_logged_but_continues(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HTTP errors in assign_strategies() are swallowed; other agents continue."""
        config = _make_config(monkeypatch)
        runner, rest, _ = self._setup_runner_with_agents(config, 3)

        call_counter: dict[str, int] = {"n": 0}

        async def _create_strategy_side_effect(**kwargs: object) -> dict[str, str]:
            n = call_counter["n"]
            call_counter["n"] += 1
            if n == 1:
                raise RuntimeError("injected failure")
            return {"strategy_id": f"strat-{n}"}

        rest.create_strategy = AsyncMock(side_effect=_create_strategy_side_effect)
        genomes = [_make_genome(i) for i in range(3)]

        # Should not raise; errors are swallowed with a warning log
        await runner.assign_strategies(genomes)

        # Agents 0 and 2 succeeded; agent 1 failed
        assert "agent-0" in runner._strategy_ids
        assert "agent-1" not in runner._strategy_ids
        assert "agent-2" in runner._strategy_ids


# ---------------------------------------------------------------------------
# TestGetFitness
# ---------------------------------------------------------------------------


class TestGetFitness:
    """Tests for BattleRunner.get_fitness() and BattleRunner._parse_metric()."""

    def _setup_runner_with_agents(
        self, config: AgentConfig, agent_ids: list[str]
    ) -> tuple[BattleRunner, MagicMock]:
        """Build a runner pre-populated with the given agent IDs."""
        rest = _mock_rest_client()
        jwt_client = MagicMock()
        runner = _build_runner(config, rest, jwt_client)
        runner._agent_ids = list(agent_ids)
        return runner, jwt_client

    def _setup_fetch(
        self, jwt_client: MagicMock, response_data: list[dict[str, object]] | dict[str, object]
    ) -> None:
        """Wire jwt_client.get to return the given data as JSON."""
        jwt_client.get = AsyncMock(return_value=_ok_response(response_data))  # type: ignore[arg-type]

    # ---- Fitness formula tests -----------------------------------------------

    async def test_fitness_formula_sharpe_minus_half_drawdown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fitness = sharpe_ratio - 0.5 * max_drawdown_pct."""
        config = _make_config(monkeypatch)
        agent_id = "agent-abc"
        runner, jwt_client = self._setup_runner_with_agents(config, [agent_id])
        results = [
            {"agent_id": agent_id, "metrics": {"sharpe_ratio": 1.5, "max_drawdown_pct": 0.2}},
        ]
        self._setup_fetch(jwt_client, results)

        fitness_map = await runner.get_fitness("battle-001")

        expected = 1.5 - 0.5 * 0.2
        assert abs(fitness_map[agent_id] - expected) < 1e-9

    async def test_fitness_sharpe_2_drawdown_0(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sharpe=2.0, drawdown=0.0 -> fitness=2.0."""
        config = _make_config(monkeypatch)
        agent_id = "agent-x"
        runner, jwt_client = self._setup_runner_with_agents(config, [agent_id])
        results = [
            {"agent_id": agent_id, "metrics": {"sharpe_ratio": 2.0, "max_drawdown_pct": 0.0}},
        ]
        self._setup_fetch(jwt_client, results)
        fitness_map = await runner.get_fitness("battle-002")
        assert abs(fitness_map[agent_id] - 2.0) < 1e-9

    async def test_fitness_negative_sharpe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative Sharpe: -0.5 - 0.5 * 0.3 = -0.65."""
        config = _make_config(monkeypatch)
        agent_id = "agent-neg"
        runner, jwt_client = self._setup_runner_with_agents(config, [agent_id])
        results = [
            {"agent_id": agent_id, "metrics": {"sharpe_ratio": -0.5, "max_drawdown_pct": 0.3}},
        ]
        self._setup_fetch(jwt_client, results)
        fitness_map = await runner.get_fitness("battle-003")
        expected = -0.5 - 0.5 * 0.3
        assert abs(fitness_map[agent_id] - expected) < 1e-9

    async def test_fitness_multiple_agents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fitness is computed independently for each agent."""
        config = _make_config(monkeypatch)
        ids = ["agent-1", "agent-2", "agent-3"]
        runner, jwt_client = self._setup_runner_with_agents(config, ids)
        results = [
            {"agent_id": "agent-1", "metrics": {"sharpe_ratio": 1.0, "max_drawdown_pct": 0.1}},
            {"agent_id": "agent-2", "metrics": {"sharpe_ratio": 2.0, "max_drawdown_pct": 0.2}},
            {"agent_id": "agent-3", "metrics": {"sharpe_ratio": 0.0, "max_drawdown_pct": 0.5}},
        ]
        self._setup_fetch(jwt_client, results)
        fitness_map = await runner.get_fitness("battle-multi")
        assert abs(fitness_map["agent-1"] - (1.0 - 0.5 * 0.1)) < 1e-9
        assert abs(fitness_map["agent-2"] - (2.0 - 0.5 * 0.2)) < 1e-9
        assert abs(fitness_map["agent-3"] - (0.0 - 0.5 * 0.5)) < 1e-9

    # ---- Fallback to ROI when sharpe is missing ------------------------------

    async def test_fitness_falls_back_to_roi_when_sharpe_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When sharpe_ratio is None, fitness falls back to roi_pct."""
        config = _make_config(monkeypatch)
        agent_id = "agent-roi"
        runner, jwt_client = self._setup_runner_with_agents(config, [agent_id])
        results = [
            {
                "agent_id": agent_id,
                "metrics": {"sharpe_ratio": None, "max_drawdown_pct": None, "roi_pct": 0.12},
            },
        ]
        self._setup_fetch(jwt_client, results)
        fitness_map = await runner.get_fitness("battle-roi")
        assert abs(fitness_map[agent_id] - 0.12) < 1e-9

    # ---- Failure fitness tests ------------------------------------------------

    async def test_failure_fitness_when_api_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All agents get FAILURE_FITNESS when the results endpoint returns []."""
        config = _make_config(monkeypatch)
        ids = ["agent-a", "agent-b"]
        runner, jwt_client = self._setup_runner_with_agents(config, ids)
        self._setup_fetch(jwt_client, [])

        fitness_map = await runner.get_fitness("battle-empty")

        for aid in ids:
            assert fitness_map[aid] == FAILURE_FITNESS

    async def test_failure_fitness_when_api_returns_http_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All agents get FAILURE_FITNESS when the results request fails."""
        config = _make_config(monkeypatch)
        ids = ["agent-x"]
        runner, jwt_client = self._setup_runner_with_agents(config, ids)
        err_resp = _error_response(500, "Internal Server Error")
        jwt_client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                message="HTTP 500",
                request=MagicMock(),
                response=err_resp,
            )
        )

        fitness_map = await runner.get_fitness("battle-fail")
        assert fitness_map["agent-x"] == FAILURE_FITNESS

    async def test_failure_fitness_when_metrics_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Agent gets FAILURE_FITNESS when metrics field is missing entirely."""
        config = _make_config(monkeypatch)
        agent_id = "agent-missing"
        runner, jwt_client = self._setup_runner_with_agents(config, [agent_id])
        results = [{"agent_id": agent_id}]  # no 'metrics' key
        self._setup_fetch(jwt_client, results)

        fitness_map = await runner.get_fitness("battle-missing")
        # Both sharpe and drawdown will be None; roi_pct also None → FAILURE_FITNESS
        assert fitness_map[agent_id] == FAILURE_FITNESS

    async def test_failure_fitness_when_agent_id_not_in_population(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Results for agents not in the population are silently skipped."""
        config = _make_config(monkeypatch)
        runner, jwt_client = self._setup_runner_with_agents(config, ["known-agent"])
        results = [
            {
                "agent_id": "unknown-agent",
                "metrics": {"sharpe_ratio": 5.0, "max_drawdown_pct": 0.1},
            },
            {
                "agent_id": "known-agent",
                "metrics": {"sharpe_ratio": 1.0, "max_drawdown_pct": 0.1},
            },
        ]
        self._setup_fetch(jwt_client, results)

        fitness_map = await runner.get_fitness("battle-unknown")
        assert "unknown-agent" not in fitness_map
        assert abs(fitness_map["known-agent"] - (1.0 - 0.5 * 0.1)) < 1e-9

    async def test_failure_fitness_sentinel_is_minus_999(self) -> None:
        """FAILURE_FITNESS constant is -999.0."""
        assert FAILURE_FITNESS == -999.0

    # ---- String metric parsing -----------------------------------------------

    async def test_fitness_with_string_metric_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Metrics serialised as strings (Decimal JSON) are parsed correctly."""
        config = _make_config(monkeypatch)
        agent_id = "agent-str"
        runner, jwt_client = self._setup_runner_with_agents(config, [agent_id])
        results = [
            {
                "agent_id": agent_id,
                "metrics": {"sharpe_ratio": "1.2", "max_drawdown_pct": "0.4"},
            },
        ]
        self._setup_fetch(jwt_client, results)

        fitness_map = await runner.get_fitness("battle-str")
        expected = 1.2 - 0.5 * 0.4
        assert abs(fitness_map[agent_id] - expected) < 1e-9

    # ---- Results wrapped in a dict -------------------------------------------

    async def test_fitness_results_wrapped_in_participants_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Results wrapped in {'participants': [...]} are unwrapped correctly."""
        config = _make_config(monkeypatch)
        agent_id = "agent-wrapped"
        runner, jwt_client = self._setup_runner_with_agents(config, [agent_id])
        wrapped = {
            "participants": [
                {
                    "agent_id": agent_id,
                    "metrics": {"sharpe_ratio": 0.8, "max_drawdown_pct": 0.15},
                }
            ]
        }
        self._setup_fetch(jwt_client, wrapped)

        fitness_map = await runner.get_fitness("battle-wrapped")
        expected = 0.8 - 0.5 * 0.15
        assert abs(fitness_map[agent_id] - expected) < 1e-9


# ---------------------------------------------------------------------------
# TestParseMetric
# ---------------------------------------------------------------------------


class TestParseMetric:
    """Unit tests for BattleRunner._parse_metric() static method."""

    def test_none_returns_none(self) -> None:
        """None input returns None."""
        assert BattleRunner._parse_metric(None) is None

    def test_integer_returns_float(self) -> None:
        """Integer input is returned as float."""
        assert BattleRunner._parse_metric(3) == 3.0
        assert isinstance(BattleRunner._parse_metric(3), float)

    def test_float_returned_as_float(self) -> None:
        """Float input is returned unchanged as float."""
        assert BattleRunner._parse_metric(1.5) == 1.5

    def test_numeric_string_parsed(self) -> None:
        """Numeric string is parsed to float."""
        assert BattleRunner._parse_metric("2.75") == 2.75

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        assert BattleRunner._parse_metric("") is None

    def test_none_string_returns_none(self) -> None:
        """String 'None' returns None."""
        assert BattleRunner._parse_metric("None") is None

    def test_null_string_returns_none(self) -> None:
        """String 'null' returns None."""
        assert BattleRunner._parse_metric("null") is None

    def test_na_string_returns_none(self) -> None:
        """String 'N/A' returns None."""
        assert BattleRunner._parse_metric("N/A") is None

    def test_non_numeric_string_returns_none(self) -> None:
        """Non-numeric string returns None."""
        assert BattleRunner._parse_metric("abc") is None

    def test_negative_float_string(self) -> None:
        """Negative float string is parsed correctly."""
        assert BattleRunner._parse_metric("-0.5") == -0.5

    def test_whitespace_string_returns_none(self) -> None:
        """Whitespace-only string is treated as empty and returns None."""
        assert BattleRunner._parse_metric("   ") is None


# ---------------------------------------------------------------------------
# TestResetAgents
# ---------------------------------------------------------------------------


class TestResetAgents:
    """Tests for BattleRunner.reset_agents()."""

    async def test_reset_posts_to_each_agent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """reset_agents() calls POST /api/v1/agents/{id}/reset for each agent."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        jwt_client = MagicMock()
        runner = _build_runner(config, rest, jwt_client)
        runner._agent_ids = ["a-001", "a-002", "a-003"]

        ok_resp = _ok_response({})
        ok_resp.raise_for_status.return_value = None
        jwt_client.post = AsyncMock(return_value=ok_resp)

        await runner.reset_agents()

        posted_urls = [call[0][0] for call in jwt_client.post.call_args_list]
        for aid in ["a-001", "a-002", "a-003"]:
            assert f"/api/v1/agents/{aid}/reset" in posted_urls

    async def test_reset_increments_generation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """reset_agents() increments the internal generation counter."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        jwt_client = MagicMock()
        runner = _build_runner(config, rest, jwt_client)
        runner._agent_ids = ["a-001"]

        jwt_client.post = AsyncMock(return_value=_ok_response({}))
        assert runner.generation == 0
        await runner.reset_agents()
        assert runner.generation == 1

    async def test_reset_http_error_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HTTP errors during reset_agents() are swallowed (not raised)."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        jwt_client = MagicMock()
        runner = _build_runner(config, rest, jwt_client)
        runner._agent_ids = ["a-fail"]

        err_resp = _error_response(500, "Server Error")
        jwt_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                message="HTTP 500",
                request=MagicMock(),
                response=err_resp,
            )
        )
        # Should not raise — failures during reset are swallowed
        await runner.reset_agents()

    async def test_reset_no_agents_is_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """reset_agents() with no agents does not make any HTTP calls."""
        config = _make_config(monkeypatch)
        rest = _mock_rest_client()
        jwt_client = MagicMock()
        jwt_client.post = AsyncMock()
        runner = _build_runner(config, rest, jwt_client)
        runner._agent_ids = []  # empty

        await runner.reset_agents()
        jwt_client.post.assert_not_called()
