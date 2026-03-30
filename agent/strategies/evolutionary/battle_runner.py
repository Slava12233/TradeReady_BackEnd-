"""BattleRunner — bridge between the genetic algorithm and the platform battle system.

Manages the full lifecycle for evaluating a population of strategy genomes
using historical agent-vs-agent battles:

1. Provisioning: create N platform agents once per experiment (``setup_agents``).
2. Reset: restore each agent to its starting balance between generations
   (``reset_agents``).
3. Strategy assignment: push each genome's strategy definition to its agent via
   the REST API (``assign_strategies``).
4. Battle execution: create a historical battle, add all agents as participants,
   start it, and drive the stepping loop until completion (``run_battle``).
5. Fitness extraction: parse the completed battle results and compute a scalar
   fitness score per agent (``get_fitness``).

Fitness formula::

    fitness = sharpe_ratio - 0.5 * max_drawdown_pct

Agents whose results are missing or malformed receive a sentinel fitness of
``-999`` so the evolutionary loop can continue without crashing.

All HTTP calls go through :class:`agent.tools.rest_tools.PlatformRESTClient`.
Battle endpoints require JWT authentication; the runner obtains a JWT on
construction by calling ``POST /api/v1/auth/login`` with the credentials in
:class:`~agent.config.AgentConfig`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from agent.config import AgentConfig
from agent.strategies.evolutionary.genome import StrategyGenome
from agent.tools.rest_tools import PlatformRESTClient

logger = structlog.get_logger(__name__)

# Sentinel fitness value assigned to any agent whose results cannot be parsed.
FAILURE_FITNESS: float = -999.0

# How many seconds to wait between battle status polls.
_POLL_INTERVAL_SECONDS: float = 5.0

# How many poll attempts to make before giving up on a battle.
_MAX_POLL_ATTEMPTS: int = 720  # 720 × 5 s = 60 minutes max


class BattleRunner:
    """Orchestrates evolutionary fitness evaluation via platform historical battles.

    Creates and manages platform agents that persist across generations.  Each
    generation assigns fresh strategy definitions derived from the current
    population of :class:`~agent.strategies.evolutionary.genome.StrategyGenome`
    objects, runs a historical battle, and returns per-agent fitness scores.

    Args:
        config: Loaded :class:`~agent.config.AgentConfig` with platform
            credentials and base URL.
        rest_client: Pre-constructed :class:`~agent.tools.rest_tools.PlatformRESTClient`
            configured for API-key auth.  The caller owns the client lifecycle
            (i.e. closing it).
        jwt_token: Optional pre-obtained JWT.  When ``None``, the runner
            will attempt to obtain one via ``POST /api/v1/auth/login`` using
            the credentials in ``config``.  Pass a token explicitly when you
            have already authenticated.

    Example::

        async with PlatformRESTClient(config) as client:
            runner = await BattleRunner.create(config, client)
            await runner.setup_agents(population_size=10)
            for generation in range(20):
                await runner.reset_agents()
                await runner.assign_strategies(population.genomes)
                battle_id = await runner.run_battle(
                    preset="historical_week",
                    historical_window=("2024-01-01T00:00:00Z", "2024-01-08T00:00:00Z"),
                )
                scores = await runner.get_fitness(battle_id)
    """

    def __init__(
        self,
        config: AgentConfig,
        rest_client: PlatformRESTClient,
        jwt_token: str,
    ) -> None:
        self._config = config
        self._rest = rest_client
        self._jwt_token = jwt_token
        self._base_url = config.platform_base_url.rstrip("/")

        # Maps genome index → platform agent_id (string UUID).
        self._agent_ids: list[str] = []

        # Maps agent_id → strategy_id created for that agent.
        self._strategy_ids: dict[str, str] = {}

        # Current generation counter (used for unique agent names).
        self._generation: int = 0

        # Shared httpx client for JWT-authenticated requests (battles, agents).
        self._jwt_client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {jwt_token}"},
            timeout=30.0,
        )

    # ── Construction ──────────────────────────────────────────────────────────

    @classmethod
    async def create(
        cls,
        config: AgentConfig,
        rest_client: PlatformRESTClient,
        jwt_token: str | None = None,
    ) -> BattleRunner:
        """Async factory: resolve JWT then construct the runner.

        If ``jwt_token`` is ``None``, authenticates using the credentials in
        ``config`` via ``POST /api/v1/auth/login``.

        Args:
            config: Platform configuration including ``platform_api_key`` and
                ``platform_api_secret``.
            rest_client: Caller-owned REST client for strategy/backtest calls.
            jwt_token: Optional pre-obtained JWT string.  When provided the
                login request is skipped.

        Returns:
            A fully-initialised :class:`BattleRunner`.

        Raises:
            RuntimeError: If JWT acquisition fails.
        """
        if jwt_token is None:
            jwt_token = await cls._acquire_jwt(config)
        return cls(config, rest_client, jwt_token)

    @staticmethod
    async def _acquire_jwt(config: AgentConfig) -> str:
        """Obtain a JWT by exchanging the API key + secret.

        Args:
            config: Config containing ``platform_api_key`` and
                ``platform_api_secret``.

        Returns:
            A JWT string.

        Raises:
            RuntimeError: On HTTP errors or missing token in the response.
        """
        url = f"{config.platform_base_url.rstrip('/')}/api/v1/auth/login"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    json={
                        "api_key": config.platform_api_key,
                        "api_secret": config.platform_api_secret,
                    },
                )
                response.raise_for_status()
                token: str = response.json()["token"]
                logger.info("agent.strategy.evolutionary.battle_runner.jwt_acquired")
                return token
        except httpx.HTTPStatusError as exc:
            msg = (
                f"JWT acquisition failed: HTTP {exc.response.status_code} — "
                f"{exc.response.text[:200]}"
            )
            logger.error("agent.strategy.evolutionary.battle_runner.jwt_failed", error=msg)
            raise RuntimeError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"JWT acquisition failed (network): {exc}"
            logger.error("agent.strategy.evolutionary.battle_runner.jwt_failed", error=msg)
            raise RuntimeError(msg) from exc
        except KeyError as exc:
            msg = "JWT acquisition failed: response did not contain 'token' key"
            logger.error("agent.strategy.evolutionary.battle_runner.jwt_failed", error=msg)
            raise RuntimeError(msg) from exc

    # ── Lifecycle helpers ─────────────────────────────────────────────────────

    async def close(self) -> None:
        """Close the internal JWT-authenticated HTTP client.

        Must be called when the runner is no longer needed, or use the runner
        as an async context manager.
        """
        await self._jwt_client.aclose()

    async def __aenter__(self) -> BattleRunner:
        """Enter the async context manager, returning self."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit the async context manager and close the JWT client."""
        await self.close()

    # ── Agent provisioning ────────────────────────────────────────────────────

    async def setup_agents(self, population_size: int) -> list[str]:
        """Create ``population_size`` platform agents and store their IDs.

        Agents are created with names ``evo-gen0-agent0``, ``evo-gen0-agent1``
        etc.  They persist across generations; call :meth:`reset_agents` to
        restore balances at the start of each new generation rather than
        creating new agents each time.

        Args:
            population_size: Number of agents to create.  Must match the size
                of the genome population passed to :meth:`assign_strategies`.

        Returns:
            List of platform agent ID strings (UUIDs) in population order.

        Raises:
            RuntimeError: If any agent creation request fails.
        """
        logger.info(
            "agent.strategy.evolutionary.battle_runner.setup_agents.start",
            population_size=population_size,
        )
        self._agent_ids = []
        names = [f"evo-gen0-agent{i}" for i in range(population_size)]

        # Gather all agent creation calls concurrently with a semaphore so we
        # do not overwhelm the platform connection pool.
        semaphore = asyncio.Semaphore(5)

        async def _create_with_semaphore(name: str) -> str:
            async with semaphore:
                return await self._create_agent(name)

        tasks = [_create_with_semaphore(name) for name in names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                msg = f"Agent creation failed for '{names[i]}': {result}"
                logger.error(
                    "agent.strategy.evolutionary.battle_runner.create_agent_failed",
                    name=names[i],
                    error=msg,
                )
                raise RuntimeError(msg) from result
            agent_id = str(result)
            self._agent_ids.append(agent_id)
            logger.debug(
                "agent.strategy.evolutionary.battle_runner.agent_created",
                index=i,
                agent_id=agent_id,
                name=names[i],
            )

        logger.info(
            "agent.strategy.evolutionary.battle_runner.setup_agents.complete",
            count=len(self._agent_ids),
        )
        return list(self._agent_ids)

    async def _create_agent(self, name: str) -> str:
        """Create a single platform agent and return its ID.

        Args:
            name: Display name for the new agent.

        Returns:
            Agent ID string (UUID).

        Raises:
            RuntimeError: On HTTP or JSON parsing errors.
        """
        body: dict[str, Any] = {
            "name": name,
            "description": "Evolutionary strategy optimisation agent",
        }
        try:
            response = await self._jwt_client.post("/api/v1/agents", json=body)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            agent_id: str = data["agent_id"]
            return agent_id
        except httpx.HTTPStatusError as exc:
            msg = (
                f"Agent creation failed for '{name}': "
                f"HTTP {exc.response.status_code} — {exc.response.text[:200]}"
            )
            logger.error("agent.strategy.evolutionary.battle_runner.create_agent_failed", name=name, error=msg)
            raise RuntimeError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"Agent creation failed for '{name}' (network): {exc}"
            logger.error("agent.strategy.evolutionary.battle_runner.create_agent_failed", name=name, error=msg)
            raise RuntimeError(msg) from exc
        except KeyError as exc:
            msg = f"Agent creation response missing 'agent_id' key for '{name}'"
            logger.error("agent.strategy.evolutionary.battle_runner.create_agent_failed", name=name, error=msg)
            raise RuntimeError(msg) from exc

    async def reset_agents(self) -> None:
        """Reset all provisioned agents to their starting balances.

        Calls ``POST /api/v1/agents/{id}/reset`` for each stored agent ID.
        Failures are logged and skipped rather than raising, so the generation
        can continue even if individual resets fail.
        """
        if not self._agent_ids:
            logger.warning("agent.strategy.evolutionary.battle_runner.reset_agents.no_agents")
            return

        logger.info(
            "agent.strategy.evolutionary.battle_runner.reset_agents.start",
            count=len(self._agent_ids),
            generation=self._generation,
        )

        # Reset all agents concurrently — each reset touches a different agent
        # record so there are no ordering dependencies.
        semaphore = asyncio.Semaphore(5)

        async def _reset_one(agent_id: str) -> None:
            async with semaphore:
                try:
                    response = await self._jwt_client.post(
                        f"/api/v1/agents/{agent_id}/reset",
                        json={"confirm": True},
                    )
                    response.raise_for_status()
                    logger.debug("agent.strategy.evolutionary.battle_runner.agent_reset", agent_id=agent_id)
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "agent.strategy.evolutionary.battle_runner.agent_reset_failed",
                        agent_id=agent_id,
                        status=exc.response.status_code,
                        body=exc.response.text[:200],
                    )
                except httpx.RequestError as exc:
                    logger.warning(
                        "agent.strategy.evolutionary.battle_runner.agent_reset_failed",
                        agent_id=agent_id,
                        error=str(exc),
                    )

        reset_tasks = [_reset_one(agent_id) for agent_id in self._agent_ids]
        await asyncio.gather(*reset_tasks, return_exceptions=True)

        self._generation += 1
        logger.info(
            "agent.strategy.evolutionary.battle_runner.reset_agents.complete",
            generation=self._generation,
        )

    # ── Strategy assignment ───────────────────────────────────────────────────

    async def assign_strategies(self, genomes: list[StrategyGenome]) -> None:
        """Create or update the strategy for each agent from its genome.

        Maps ``genomes[i]`` to ``self._agent_ids[i]``.  For each agent, either
        creates a new strategy (first generation) or creates a new version of
        the existing strategy (subsequent generations).

        Args:
            genomes: Ordered list of :class:`~StrategyGenome` objects.  Must
                have the same length as :attr:`_agent_ids`.

        Raises:
            ValueError: If ``len(genomes) != len(self._agent_ids)``.
        """
        if len(genomes) != len(self._agent_ids):
            msg = (
                f"Genome count ({len(genomes)}) must match agent count "
                f"({len(self._agent_ids)})"
            )
            raise ValueError(msg)

        logger.info(
            "agent.strategy.evolutionary.battle_runner.assign_strategies.start",
            count=len(genomes),
            generation=self._generation,
        )

        # Capture generation at the point of dispatch so all concurrent tasks
        # use the same generation value even if reset_agents() increments it
        # during an overlapping call (defensive — callers should not overlap).
        current_generation = self._generation

        semaphore = asyncio.Semaphore(5)

        async def _assign_one(i: int, genome: StrategyGenome, agent_id: str) -> None:
            definition = genome.to_strategy_definition()
            strategy_name = f"evo-gen{current_generation}-agent{i}"
            async with semaphore:
                try:
                    if agent_id not in self._strategy_ids:
                        # First generation: create a new strategy.
                        strategy_id = await self._create_strategy_for_agent(
                            agent_id=agent_id,
                            name=strategy_name,
                            definition=definition,
                        )
                        # Dict write is safe: each task touches a different key.
                        self._strategy_ids[agent_id] = strategy_id
                        logger.debug(
                            "agent.strategy.evolutionary.battle_runner.strategy_created",
                            agent_id=agent_id,
                            strategy_id=strategy_id,
                            generation=current_generation,
                        )
                    else:
                        # Subsequent generation: create a new version.
                        strategy_id = self._strategy_ids[agent_id]
                        await self._create_strategy_version(
                            strategy_id=strategy_id,
                            definition=definition,
                            generation=current_generation,
                        )
                        logger.debug(
                            "agent.strategy.evolutionary.battle_runner.strategy_version_created",
                            agent_id=agent_id,
                            strategy_id=strategy_id,
                            generation=current_generation,
                        )
                except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as exc:
                    logger.warning(
                        "agent.strategy.evolutionary.battle_runner.assign_strategy_failed",
                        agent_id=agent_id,
                        index=i,
                        error=str(exc),
                    )
                    # Continue with other agents rather than aborting.

        assign_tasks = [
            _assign_one(i, genome, agent_id)
            for i, (genome, agent_id) in enumerate(zip(genomes, self._agent_ids))
        ]
        await asyncio.gather(*assign_tasks, return_exceptions=True)

        logger.info(
            "agent.strategy.evolutionary.battle_runner.assign_strategies.complete",
            generation=self._generation,
        )

    async def _create_strategy_for_agent(
        self,
        agent_id: str,
        name: str,
        definition: dict[str, Any],
    ) -> str:
        """Create a new strategy for an agent and return the strategy_id.

        Uses ``POST /api/v1/strategies`` with the API-key client (strategies
        endpoint accepts both API key and JWT).

        Args:
            agent_id: Unused directly (for logging context only).
            name: Human-readable strategy name.
            definition: Platform-compatible strategy definition dict.

        Returns:
            Strategy ID string.

        Raises:
            RuntimeError: On HTTP or parsing errors.
        """
        result = await self._rest.create_strategy(
            name=name,
            description=f"Evolutionary genome for agent {agent_id} gen {self._generation}",
            definition=definition,
        )
        if "error" in result:
            msg = f"Strategy creation failed: {result['error']}"
            raise RuntimeError(msg)
        try:
            return str(result["strategy_id"])
        except KeyError as exc:
            msg = f"Strategy creation response missing 'strategy_id': {result}"
            raise RuntimeError(msg) from exc

    async def _create_strategy_version(
        self,
        strategy_id: str,
        definition: dict[str, Any],
        generation: int,
    ) -> None:
        """Create a new version of an existing strategy.

        Args:
            strategy_id: Platform strategy UUID.
            definition: Updated strategy definition dict.
            generation: Current generation number (included in change notes).
        """
        result = await self._rest.create_version(
            strategy_id=strategy_id,
            definition=definition,
            change_notes=f"Evolutionary optimisation — generation {generation}",
        )
        if "error" in result:
            logger.warning(
                "agent.strategy.evolutionary.battle_runner.strategy_version_failed",
                strategy_id=strategy_id,
                error=result["error"],
            )

    # ── Battle lifecycle ──────────────────────────────────────────────────────

    async def run_battle(
        self,
        preset: str,
        historical_window: tuple[str, str],
    ) -> str:
        """Create, configure, and run a historical battle to completion.

        Steps:
        1. Create a battle in draft state using the supplied preset.
        2. Add all provisioned agents as participants.
        3. Start the battle.
        4. Drive the stepping loop until ``is_complete`` is ``True`` or the
           battle transitions to ``completed`` status.
        5. Stop the battle to finalise rankings.

        Args:
            preset: Battle preset key (e.g. ``"historical_week"``).  Must be
                one of the 3 historical presets: ``historical_day``,
                ``historical_week``, ``historical_month``.
            historical_window: ``(start_iso, end_iso)`` ISO-8601 timestamps
                defining the replay period (e.g.
                ``("2024-01-01T00:00:00Z", "2024-01-08T00:00:00Z")``).

        Returns:
            The battle ID string (UUID) of the completed battle.

        Raises:
            RuntimeError: If battle creation, participant addition, or start
                fails with a non-recoverable error.
        """
        start_time, end_time = historical_window

        # Step 1: Create battle.
        battle_id = await self._create_battle(preset, start_time, end_time)
        logger.info(
            "agent.strategy.evolutionary.battle_runner.battle_created",
            battle_id=battle_id,
            preset=preset,
            start=start_time,
            end=end_time,
        )

        # Step 2: Add participants.
        await self._add_participants(battle_id)
        logger.info(
            "agent.strategy.evolutionary.battle_runner.participants_added",
            battle_id=battle_id,
            count=len(self._agent_ids),
        )

        # Step 3: Start battle.
        await self._start_battle(battle_id)
        logger.info("agent.strategy.evolutionary.battle_runner.battle_started", battle_id=battle_id)

        # Step 4: Drive stepping loop.
        await self._run_step_loop(battle_id)
        logger.info("agent.strategy.evolutionary.battle_runner.step_loop_complete", battle_id=battle_id)

        # Step 5: Stop battle to calculate rankings.
        await self._stop_battle(battle_id)
        logger.info("agent.strategy.evolutionary.battle_runner.battle_stopped", battle_id=battle_id)

        return battle_id

    async def _create_battle(
        self,
        preset: str,
        start_time: str,
        end_time: str,
    ) -> str:
        """Create a new draft battle and return its ID.

        Args:
            preset: Preset key for the battle configuration.
            start_time: ISO-8601 start of the historical window.
            end_time: ISO-8601 end of the historical window.

        Returns:
            Battle ID string.

        Raises:
            RuntimeError: On HTTP or parsing errors.
        """
        body: dict[str, Any] = {
            "name": f"evo-gen{self._generation}-battle",
            "preset": preset,
            "battle_mode": "historical",
            "backtest_config": {
                "start_time": start_time,
                "end_time": end_time,
            },
        }
        try:
            response = await self._jwt_client.post("/api/v1/battles", json=body)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            battle_id: str = data["battle_id"]
            return battle_id
        except httpx.HTTPStatusError as exc:
            msg = (
                f"Battle creation failed: "
                f"HTTP {exc.response.status_code} — {exc.response.text[:200]}"
            )
            logger.error("agent.strategy.evolutionary.battle_runner.create_battle_failed", error=msg)
            raise RuntimeError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"Battle creation failed (network): {exc}"
            logger.error("agent.strategy.evolutionary.battle_runner.create_battle_failed", error=msg)
            raise RuntimeError(msg) from exc
        except KeyError as exc:
            msg = "Battle creation response missing 'battle_id' key"
            logger.error("agent.strategy.evolutionary.battle_runner.create_battle_failed", error=msg)
            raise RuntimeError(msg) from exc

    async def _add_participants(self, battle_id: str) -> None:
        """Add all provisioned agents as battle participants.

        Args:
            battle_id: UUID of the target battle.

        Raises:
            RuntimeError: If any participant cannot be added.
        """
        # Register all participants concurrently.  Each registration is
        # independent (different agent_id).  Use a semaphore to avoid
        # overwhelming the battle service connection pool.
        semaphore = asyncio.Semaphore(5)

        async def _register_one(agent_id: str) -> None:
            async with semaphore:
                try:
                    response = await self._jwt_client.post(
                        f"/api/v1/battles/{battle_id}/participants",
                        json={"agent_id": agent_id},
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    msg = (
                        f"Failed to add agent {agent_id} to battle {battle_id}: "
                        f"HTTP {exc.response.status_code} — {exc.response.text[:200]}"
                    )
                    logger.error("agent.strategy.evolutionary.battle_runner.add_participant_failed", error=msg)
                    raise RuntimeError(msg) from exc
                except httpx.RequestError as exc:
                    msg = f"Failed to add agent {agent_id} (network): {exc}"
                    logger.error("agent.strategy.evolutionary.battle_runner.add_participant_failed", error=msg)
                    raise RuntimeError(msg) from exc

        participant_tasks = [_register_one(agent_id) for agent_id in self._agent_ids]
        results = await asyncio.gather(*participant_tasks, return_exceptions=True)

        # Re-raise the first exception encountered so the caller can abort.
        for result in results:
            if isinstance(result, Exception):
                raise result

    async def _start_battle(self, battle_id: str) -> None:
        """Start a pending battle.

        Args:
            battle_id: UUID of the battle to start.

        Raises:
            RuntimeError: On HTTP errors.
        """
        try:
            response = await self._jwt_client.post(
                f"/api/v1/battles/{battle_id}/start"
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            msg = (
                f"Battle start failed for {battle_id}: "
                f"HTTP {exc.response.status_code} — {exc.response.text[:200]}"
            )
            logger.error("agent.strategy.evolutionary.battle_runner.start_battle_failed", error=msg)
            raise RuntimeError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"Battle start failed for {battle_id} (network): {exc}"
            logger.error("agent.strategy.evolutionary.battle_runner.start_battle_failed", error=msg)
            raise RuntimeError(msg) from exc

    async def _run_step_loop(self, battle_id: str) -> None:
        """Drive the historical battle stepping loop until completion.

        Polls ``POST /api/v1/battles/{id}/step`` in a loop.  Each call
        advances the shared virtual clock by one candle interval for all
        participants.  Sleeps :data:`_POLL_INTERVAL_SECONDS` between steps to
        avoid hammering the server with fast sequential requests.

        Exits when:
        - The step response contains ``is_complete: true``.
        - The battle status (from ``GET /api/v1/battles/{id}``) becomes
          ``"completed"``.
        - :data:`_MAX_POLL_ATTEMPTS` are exhausted (safety guard).

        Args:
            battle_id: UUID of the active battle.
        """
        logger.info(
            "agent.strategy.evolutionary.battle_runner.step_loop.start",
            battle_id=battle_id,
            max_attempts=_MAX_POLL_ATTEMPTS,
        )

        for attempt in range(_MAX_POLL_ATTEMPTS):
            try:
                response = await self._jwt_client.post(
                    f"/api/v1/battles/{battle_id}/step"
                )
                response.raise_for_status()
                data: dict[str, Any] = response.json()

                progress = data.get("progress_pct", 0)
                step = data.get("step", attempt)
                total = data.get("total_steps", "?")
                is_complete: bool = bool(data.get("is_complete", False))

                if attempt % 20 == 0 or is_complete:
                    logger.info(
                        "agent.strategy.evolutionary.battle_runner.step_loop.progress",
                        battle_id=battle_id,
                        step=step,
                        total=total,
                        progress_pct=progress,
                        is_complete=is_complete,
                    )

                if is_complete:
                    logger.info(
                        "agent.strategy.evolutionary.battle_runner.step_loop.complete",
                        battle_id=battle_id,
                        total_steps=step,
                    )
                    return

            except httpx.HTTPStatusError as exc:
                # 409 Conflict usually means the battle has already completed
                # server-side; treat it as a completion signal.
                if exc.response.status_code == 409:
                    logger.info(
                        "agent.strategy.evolutionary.battle_runner.step_loop.already_complete",
                        battle_id=battle_id,
                        attempt=attempt,
                    )
                    return
                logger.warning(
                    "agent.strategy.evolutionary.battle_runner.step_loop.http_error",
                    battle_id=battle_id,
                    status=exc.response.status_code,
                    body=exc.response.text[:200],
                    attempt=attempt,
                )
                # Treat 5xx errors as transient; continue polling.
                if exc.response.status_code >= 500:
                    await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                    continue
                # 4xx other than 409 are non-recoverable.
                msg = (
                    f"Step loop failed for battle {battle_id}: "
                    f"HTTP {exc.response.status_code}"
                )
                raise RuntimeError(msg) from exc

            except httpx.RequestError as exc:
                logger.warning(
                    "agent.strategy.evolutionary.battle_runner.step_loop.network_error",
                    battle_id=battle_id,
                    error=str(exc),
                    attempt=attempt,
                )
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                continue

            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

        logger.warning(
            "agent.strategy.evolutionary.battle_runner.step_loop.timeout",
            battle_id=battle_id,
            max_attempts=_MAX_POLL_ATTEMPTS,
        )

    async def _stop_battle(self, battle_id: str) -> None:
        """Stop the battle and trigger final ranking calculation.

        Args:
            battle_id: UUID of the battle to stop.
        """
        try:
            response = await self._jwt_client.post(
                f"/api/v1/battles/{battle_id}/stop"
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # If the battle is already completed, the stop call may return 409.
            # Treat this as success.
            if exc.response.status_code == 409:
                logger.debug(
                    "agent.strategy.evolutionary.battle_runner.stop_battle.already_stopped",
                    battle_id=battle_id,
                )
                return
            msg = (
                f"Battle stop failed for {battle_id}: "
                f"HTTP {exc.response.status_code} — {exc.response.text[:200]}"
            )
            logger.error("agent.strategy.evolutionary.battle_runner.stop_battle_failed", error=msg)
            raise RuntimeError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"Battle stop failed for {battle_id} (network): {exc}"
            logger.error("agent.strategy.evolutionary.battle_runner.stop_battle_failed", error=msg)
            raise RuntimeError(msg) from exc

    # ── Fitness extraction ────────────────────────────────────────────────────

    async def get_fitness(self, battle_id: str) -> dict[str, float]:
        """Fetch battle results and compute fitness scores for each agent.

        Legacy fitness formula (used when ``fitness_fn != 'composite'``)::

            fitness = sharpe_ratio - 0.5 * max_drawdown_pct

        Agents with missing or malformed results receive
        :data:`FAILURE_FITNESS` (``-999``).

        Args:
            battle_id: UUID of a completed battle.

        Returns:
            Dict mapping agent_id → fitness score.  Contains an entry for
            every agent in :attr:`_agent_ids`.
        """
        detailed = await self.get_detailed_metrics(battle_id)
        fitness_map: dict[str, float] = {}

        for agent_id in self._agent_ids:
            m = detailed.get(agent_id)
            if m is None:
                fitness_map[agent_id] = FAILURE_FITNESS
                continue

            sharpe = m.get("sharpe_ratio")
            drawdown = m.get("max_drawdown_pct")

            if sharpe is None or drawdown is None:
                roi = m.get("roi_pct")
                fitness_map[agent_id] = float(roi) if roi is not None else FAILURE_FITNESS
            else:
                fitness_map[agent_id] = float(sharpe) - 0.5 * float(drawdown)

        logger.info(
            "agent.strategy.evolutionary.battle_runner.get_fitness.complete",
            battle_id=battle_id,
            scores={aid: round(f, 4) for aid, f in fitness_map.items()},
        )
        return fitness_map

    async def get_detailed_metrics(
        self, battle_id: str
    ) -> dict[str, dict[str, float | None]]:
        """Fetch battle results and return the full per-agent metrics dict.

        Unlike :meth:`get_fitness` (which reduces to a scalar), this method
        returns all available metrics for each agent so callers can compute
        richer fitness functions (e.g. the 5-factor composite that includes
        ``profit_factor``, ``win_rate``, and an OOS Sharpe overlay).

        Metrics included per agent (all ``float | None``):

        - ``sharpe_ratio``
        - ``max_drawdown_pct``
        - ``profit_factor`` — gross profit / gross loss; ``None`` if no trades
        - ``win_rate`` — fraction of trades that closed at a profit [0, 1]
        - ``roi_pct`` — percentage return on initial capital

        Args:
            battle_id: UUID of a completed battle.

        Returns:
            Dict mapping agent_id → ``{metric_name: value}`` for every agent
            in :attr:`_agent_ids`.  Agents with missing results receive a dict
            of all-``None`` values rather than :data:`FAILURE_FITNESS` so the
            caller can distinguish "missing" from "zero".
        """
        logger.info(
            "agent.strategy.evolutionary.battle_runner.get_detailed_metrics.start",
            battle_id=battle_id,
        )

        null_metrics: dict[str, float | None] = {
            "sharpe_ratio": None,
            "max_drawdown_pct": None,
            "profit_factor": None,
            "win_rate": None,
            "roi_pct": None,
        }

        result_map: dict[str, dict[str, float | None]] = {
            aid: dict(null_metrics) for aid in self._agent_ids
        }

        raw_results = await self._fetch_battle_results(battle_id)

        if not raw_results:
            logger.warning(
                "agent.strategy.evolutionary.battle_runner.get_detailed_metrics.no_results",
                battle_id=battle_id,
            )
            return result_map

        participants: list[dict[str, Any]] = raw_results if isinstance(raw_results, list) else []
        if not participants:
            if isinstance(raw_results, dict):
                participants = raw_results.get("participants", raw_results.get("results", []))

        for result in participants:
            agent_id_raw = result.get("agent_id")
            if agent_id_raw is None:
                continue
            agent_id = str(agent_id_raw)
            if agent_id not in result_map:
                continue

            try:
                metrics_raw = result.get("metrics")
                # Guard: if "metrics" is present but is not a dict (e.g. a
                # malformed string value from the API), fall back to the
                # top-level result dict so metric lookups still work.
                metrics: dict[str, Any] = (
                    metrics_raw
                    if isinstance(metrics_raw, dict)
                    else result
                )
                extracted: dict[str, float | None] = {
                    "sharpe_ratio": self._parse_metric(metrics.get("sharpe_ratio")),
                    "max_drawdown_pct": self._parse_metric(metrics.get("max_drawdown_pct")),
                    "profit_factor": self._parse_metric(
                        metrics.get("profit_factor") or result.get("profit_factor")
                    ),
                    "win_rate": self._parse_metric(
                        metrics.get("win_rate") or result.get("win_rate")
                    ),
                    "roi_pct": self._parse_metric(
                        metrics.get("roi_pct") or result.get("roi_pct")
                    ),
                }
                result_map[agent_id] = extracted
                logger.debug(
                    "agent.strategy.evolutionary.battle_runner.detailed_metrics_extracted",
                    agent_id=agent_id,
                    **{k: (round(v, 4) if v is not None else None) for k, v in extracted.items()},
                )
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "agent.strategy.evolutionary.battle_runner.detailed_metrics_parse_error",
                    agent_id=agent_id,
                    error=str(exc),
                )
                # Leave the all-None entry for this agent.

        logger.info(
            "agent.strategy.evolutionary.battle_runner.get_detailed_metrics.complete",
            battle_id=battle_id,
            agent_count=len(result_map),
        )
        return result_map

    async def _fetch_battle_results(
        self, battle_id: str
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Fetch raw battle results from ``GET /api/v1/battles/{id}/results``.

        Args:
            battle_id: UUID of the completed battle.

        Returns:
            Parsed JSON response (list or dict).  Returns an empty list on
            error so callers assign failure fitness rather than crashing.
        """
        try:
            response = await self._jwt_client.get(
                f"/api/v1/battles/{battle_id}/results"
            )
            response.raise_for_status()
            data = response.json()
            return data  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "agent.strategy.evolutionary.battle_runner.fetch_results_failed",
                battle_id=battle_id,
                status=exc.response.status_code,
                body=exc.response.text[:200],
            )
            return []
        except httpx.RequestError as exc:
            logger.warning(
                "agent.strategy.evolutionary.battle_runner.fetch_results_failed",
                battle_id=battle_id,
                error=str(exc),
            )
            return []

    @staticmethod
    def _parse_metric(value: int | float | str | None) -> float | None:
        """Parse a metric value that may be a string, float, int, or None.

        The platform serialises :class:`~decimal.Decimal` fields as strings in
        JSON responses.  This helper converts ``"None"``, ``"null"``, and empty
        strings to ``None`` so fitness computation can fall back gracefully.

        Args:
            value: Raw metric value from the API response.

        Returns:
            Parsed float, or ``None`` if the value is missing or
            non-numeric.
        """
        if value is None:
            return None
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped in ("", "None", "null", "N/A"):
                return None
            try:
                return float(stripped)
            except ValueError:
                return None
        return None

    # ── Cleanup ───────────────────────────────────────────────────────────────

    async def cleanup(self, battle_id: str) -> None:
        """Attempt to delete a completed battle.

        This is optional housekeeping.  Failures are logged and swallowed —
        the evolutionary loop should not stop because of a cleanup error.

        Args:
            battle_id: UUID of the battle to delete.
        """
        try:
            response = await self._jwt_client.delete(
                f"/api/v1/battles/{battle_id}"
            )
            response.raise_for_status()
            logger.info("agent.strategy.evolutionary.battle_runner.cleanup.complete", battle_id=battle_id)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "agent.strategy.evolutionary.battle_runner.cleanup_failed",
                battle_id=battle_id,
                status=exc.response.status_code,
                body=exc.response.text[:200],
            )
        except httpx.RequestError as exc:
            logger.warning(
                "agent.strategy.evolutionary.battle_runner.cleanup_failed",
                battle_id=battle_id,
                error=str(exc),
            )

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def agent_ids(self) -> list[str]:
        """Ordered list of provisioned platform agent IDs.

        Returns:
            Copy of the internal agent ID list.
        """
        return list(self._agent_ids)

    @property
    def generation(self) -> int:
        """Current generation counter (incremented by :meth:`reset_agents`).

        Returns:
            Current generation index.
        """
        return self._generation
