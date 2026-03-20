"""Evolution loop orchestrator — runs N generations of genetic algorithm optimisation.

CLI entry point::

    python -m agent.strategies.evolutionary.evolve --generations 30 --pop-size 12

The script:

1. Parses CLI arguments (``--generations``, ``--pop-size``, ``--seed``, etc.).
2. Loads :class:`EvolutionConfig` from environment / ``agent/.env``.
3. Applies CLI overrides on top of the config.
4. Initialises a :class:`Population` of random :class:`StrategyGenome` objects.
5. Provisions platform agents via :class:`BattleRunner` (once, before gen 0).
6. For each generation:
   a. Resets agent balances.
   b. Assigns current genome population as agent strategies.
   c. Runs a historical battle and extracts per-agent fitness scores.
   d. Logs gen #, best/avg/worst fitness, and the champion genome's key params.
   e. Checks convergence: stops early if no improvement for
      ``config.convergence_threshold`` consecutive generations.
   f. Saves the champion genome as a new strategy version via the REST API.
   g. Evolves the population → next generation.
7. Writes ``results/evolution_log.json`` and ``results/champion.json`` to disk.

Battle failures are caught per-generation: the generation is skipped (fitness
scores default to -999), the error is logged, and the loop continues.  This
prevents a single HTTP error from aborting a multi-hour optimisation run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from agent.config import AgentConfig
from agent.strategies.evolutionary.battle_runner import BattleRunner, FAILURE_FITNESS
from agent.strategies.evolutionary.config import EvolutionConfig
from agent.strategies.evolutionary.genome import StrategyGenome
from agent.strategies.evolutionary.population import Population, PopulationStats
from agent.tools.rest_tools import PlatformRESTClient

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_RESULTS_DIR: Path = Path(__file__).parent / "results"
_EVOLUTION_LOG_PATH: Path = _RESULTS_DIR / "evolution_log.json"
_CHAMPION_PATH: Path = _RESULTS_DIR / "champion.json"


# ---------------------------------------------------------------------------
# Fitness computation (allows swapping the fitness function at runtime)
# ---------------------------------------------------------------------------

def _compute_fitness(
    agent_ids: list[str],
    raw_scores: dict[str, float],
    fitness_fn: str,
) -> list[float]:
    """Map raw battle scores to a fitness list aligned with agent_ids.

    The ``BattleRunner.get_fitness`` method already applies the default
    ``sharpe - 0.5 * drawdown`` formula.  This function maps the returned
    dict to the ordered list that :class:`Population` expects, and optionally
    reweights when a non-default fitness function is requested.

    Currently only ``sharpe_minus_drawdown`` is supported end-to-end (since
    the raw scores from the battle runner already encode that formula).
    ``sharpe_only`` and ``roi_only`` require the runner to return richer
    data; for now they fall back to the raw score.

    Args:
        agent_ids: Ordered list of platform agent IDs matching the population.
        raw_scores: ``{agent_id: fitness}`` map from :meth:`BattleRunner.get_fitness`.
        fitness_fn: Fitness function identifier from :class:`EvolutionConfig`.

    Returns:
        Ordered list of float fitness values, one per genome.
    """
    _ = fitness_fn  # reserved for future reweighting logic
    return [raw_scores.get(aid, FAILURE_FITNESS) for aid in agent_ids]


# ---------------------------------------------------------------------------
# Champion persistence helpers
# ---------------------------------------------------------------------------

def _genome_to_loggable(genome: StrategyGenome) -> dict[str, Any]:
    """Serialise a genome to a JSON-safe dict for logging and disk output.

    Args:
        genome: The genome to serialise.

    Returns:
        A dict with all genome fields; list values (pairs) are already JSON-safe.
    """
    return {
        "rsi_oversold": genome.rsi_oversold,
        "rsi_overbought": genome.rsi_overbought,
        "macd_fast": genome.macd_fast,
        "macd_slow": genome.macd_slow,
        "adx_threshold": genome.adx_threshold,
        "stop_loss_pct": genome.stop_loss_pct,
        "take_profit_pct": genome.take_profit_pct,
        "trailing_stop_pct": genome.trailing_stop_pct,
        "position_size_pct": genome.position_size_pct,
        "max_hold_candles": genome.max_hold_candles,
        "max_positions": genome.max_positions,
        "pairs": genome.pairs,
    }


def _save_json(path: Path, data: Any) -> None:
    """Write ``data`` to ``path`` as pretty-printed JSON.

    Creates parent directories if they do not exist.  Overwrites any existing
    file silently.

    Args:
        path: Absolute path to the output file.
        data: JSON-serialisable object.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("evolve.saved_file", path=str(path))


# Module-level variable that tracks the platform strategy ID created for the
# champion genome during the current evolution run.  Reset to None at the
# start of each run via run_evolution() so multiple runs in the same process
# do not share state.
_champion_strategy_id: str | None = None


async def _save_champion_strategy(
    rest_client: PlatformRESTClient,
    champion: StrategyGenome,
    generation: int,
    fitness: float,
) -> str | None:
    """Create a platform strategy version for the champion genome.

    On the first call a new strategy is created.  On subsequent calls
    a new version is appended to the same strategy.  The strategy ID is
    stored in the module-level ``_champion_strategy_id`` variable so it
    persists across calls within one evolution run and is reset between runs.

    Args:
        rest_client: API-key authenticated REST client.
        champion: The best genome found so far.
        generation: Current generation index (0-based) for naming.
        fitness: Best fitness score, included in change notes.

    Returns:
        The platform strategy ID string on success, ``None`` on failure.
    """
    global _champion_strategy_id

    definition = champion.to_strategy_definition()
    name = f"evo-champion-gen{generation}"
    description = (
        f"Evolutionary champion — generation {generation}, "
        f"fitness {fitness:.4f}"
    )

    strategy_id: str | None = _champion_strategy_id

    try:
        if strategy_id is None:
            result = await rest_client.create_strategy(
                name=name,
                description=description,
                definition=definition,
            )
            if "error" in result:
                logger.warning(
                    "evolve.champion_strategy_save_failed",
                    generation=generation,
                    error=result["error"],
                )
                return None
            strategy_id = str(result.get("strategy_id", ""))
            _champion_strategy_id = strategy_id
            logger.info(
                "evolve.champion_strategy_created",
                strategy_id=strategy_id,
                generation=generation,
            )
        else:
            change_notes = (
                f"Evolutionary champion update — generation {generation}, "
                f"fitness {fitness:.4f}"
            )
            result = await rest_client.create_version(
                strategy_id=strategy_id,
                definition=definition,
                change_notes=change_notes,
            )
            if "error" in result:
                logger.warning(
                    "evolve.champion_version_save_failed",
                    strategy_id=strategy_id,
                    generation=generation,
                    error=result["error"],
                )
                # Non-fatal: return the existing strategy_id anyway.
            else:
                logger.info(
                    "evolve.champion_version_created",
                    strategy_id=strategy_id,
                    generation=generation,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "evolve.champion_strategy_exception",
            generation=generation,
            error=str(exc),
        )
        return None

    return strategy_id


# ---------------------------------------------------------------------------
# Convergence detector
# ---------------------------------------------------------------------------

class ConvergenceDetector:
    """Tracks best fitness across generations and signals when to stop early.

    Args:
        threshold: Number of consecutive generations with no improvement
            before :meth:`converged` returns ``True``.
        min_improvement: Minimum absolute improvement in best fitness that
            resets the plateau counter.  Default 1e-4 avoids triggering on
            floating-point noise.
    """

    def __init__(self, threshold: int, min_improvement: float = 1e-4) -> None:
        self._threshold = threshold
        self._min_improvement = min_improvement
        self._best: float = float("-inf")
        self._stale_gens: int = 0

    def update(self, best_fitness: float) -> None:
        """Register the best fitness for the current generation.

        Args:
            best_fitness: The highest fitness value observed this generation.
        """
        if best_fitness - self._best >= self._min_improvement:
            self._best = best_fitness
            self._stale_gens = 0
        else:
            self._stale_gens += 1

    @property
    def converged(self) -> bool:
        """``True`` when the plateau counter has reached the threshold.

        Returns:
            Whether early stopping should be triggered.
        """
        return self._stale_gens >= self._threshold

    @property
    def stale_generations(self) -> int:
        """Number of consecutive generations with no meaningful improvement.

        Returns:
            Current stale generation count.
        """
        return self._stale_gens


# ---------------------------------------------------------------------------
# Main evolution loop
# ---------------------------------------------------------------------------

async def run_evolution(cfg: EvolutionConfig) -> dict[str, Any]:
    """Execute the full genetic algorithm loop.

    Initialises the population, provisions battle agents, then iterates for
    up to ``cfg.generations`` generations.  Each generation runs a historical
    battle for fitness evaluation, logs statistics, checks for convergence,
    and evolves the population.

    Args:
        cfg: Fully-resolved :class:`EvolutionConfig` with all hyperparameters.

    Returns:
        A JSON-serialisable summary dict containing the champion genome,
        per-generation stats, and final metadata.  This dict is written to
        ``results/evolution_log.json`` by the caller.
    """
    global _champion_strategy_id
    # Reset the module-level strategy ID so each run starts fresh and cannot
    # accidentally re-use a strategy ID from a previous run in the same process.
    _champion_strategy_id = None

    agent_cfg = AgentConfig()  # reads agent/.env

    # Initialise population with deterministic seed.
    population = Population(
        size=cfg.population_size,
        seed=cfg.seed,
        mutation_rate=cfg.mutation_rate,
        mutation_strength=cfg.mutation_strength,
        elite_pct=cfg.elite_pct,
    )
    population.initialize()

    convergence = ConvergenceDetector(threshold=cfg.convergence_threshold)

    # Per-generation records for the evolution log.
    generation_log: list[dict[str, Any]] = []

    # Track the overall champion across all generations.
    champion_genome: StrategyGenome = population.genomes[0]
    champion_fitness: float = float("-inf")
    champion_generation: int = 0

    async with PlatformRESTClient(agent_cfg) as rest_client:
        runner = await BattleRunner.create(agent_cfg, rest_client)
        async with runner:
            # One-time provisioning of battle agents.
            await runner.setup_agents(cfg.population_size)
            logger.info(
                "evolve.agents_provisioned",
                count=cfg.population_size,
            )

            for gen_idx in range(cfg.generations):
                gen_number = gen_idx + 1  # 1-based for display
                log = logger.bind(gen=gen_number, total=cfg.generations)

                battle_id: str | None = None
                fitness_scores: list[float] = [FAILURE_FITNESS] * cfg.population_size

                try:
                    # Step a: Reset agent balances.
                    await runner.reset_agents()

                    # Step b: Assign current population genomes as strategies.
                    await runner.assign_strategies(population.genomes)

                    # Step c: Run the historical battle and get fitness scores.
                    battle_id = await runner.run_battle(
                        preset=cfg.battle_preset,
                        historical_window=cfg.historical_window,
                    )
                    raw_scores = await runner.get_fitness(battle_id)
                    fitness_scores = _compute_fitness(
                        runner.agent_ids,
                        raw_scores,
                        cfg.fitness_fn,
                    )

                    # Optional housekeeping — best-effort cleanup.
                    await runner.cleanup(battle_id)

                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "evolve.generation_failed",
                        error=str(exc),
                        battle_id=battle_id,
                    )
                    # Skip evolution for this generation; fitness stays at -999.

                # Step d: Compute stats and log.
                stats: PopulationStats = population.stats(fitness_scores)
                best_genome: StrategyGenome = population.best(fitness_scores)

                log.info(
                    "evolve.generation_stats",
                    best=round(stats.best, 4),
                    avg=round(stats.mean, 4),
                    worst=round(stats.worst, 4),
                    stale=convergence.stale_generations,
                )

                # Structured log matching the required format:
                # "gen 15/30 | best: 1.42 | avg: 0.87 | worst: -0.23"
                print(  # noqa: T201
                    f"gen {gen_number}/{cfg.generations} | "
                    f"best: {stats.best:.2f} | "
                    f"avg: {stats.mean:.2f} | "
                    f"worst: {stats.worst:.2f}"
                )

                # Update overall champion.
                if stats.best > champion_fitness:
                    champion_genome = best_genome
                    champion_fitness = stats.best
                    champion_generation = gen_idx

                # Step e: Check convergence before evolving.
                convergence.update(stats.best)

                # Step f: Save champion genome as a new strategy version.
                await _save_champion_strategy(
                    rest_client=rest_client,
                    champion=champion_genome,
                    generation=gen_idx,
                    fitness=champion_fitness,
                )

                # Record generation entry for the evolution log.
                gen_record: dict[str, Any] = {
                    "generation": gen_number,
                    "best_fitness": round(stats.best, 6),
                    "avg_fitness": round(stats.mean, 6),
                    "worst_fitness": round(stats.worst, 6),
                    "std_fitness": round(stats.std, 6),
                    "stale_generations": convergence.stale_generations,
                    "battle_id": battle_id,
                    "champion_params": _genome_to_loggable(best_genome),
                }
                generation_log.append(gen_record)

                if convergence.converged:
                    log.info(
                        "evolve.converged",
                        threshold=cfg.convergence_threshold,
                        stale=convergence.stale_generations,
                        gen=gen_number,
                    )
                    print(  # noqa: T201
                        f"[converged] no improvement for "
                        f"{cfg.convergence_threshold} generations — stopping early "
                        f"at gen {gen_number}/{cfg.generations}"
                    )
                    break

                # Step g: Evolve population → next generation (skip after last gen).
                if gen_number < cfg.generations:
                    population.evolve(fitness_scores)

    # Build the final summary.
    summary: dict[str, Any] = {
        "run_timestamp": datetime.now(UTC).isoformat(),
        "config": {
            "population_size": cfg.population_size,
            "generations_planned": cfg.generations,
            "generations_run": len(generation_log),
            "elite_pct": cfg.elite_pct,
            "mutation_rate": cfg.mutation_rate,
            "mutation_strength": cfg.mutation_strength,
            "battle_preset": cfg.battle_preset,
            "historical_start": str(cfg.historical_start),
            "historical_end": str(cfg.historical_end),
            "convergence_threshold": cfg.convergence_threshold,
            "fitness_fn": cfg.fitness_fn,
            "seed": cfg.seed,
        },
        "champion": {
            "generation": champion_generation + 1,  # 1-based
            "fitness": round(champion_fitness, 6),
            "genome": _genome_to_loggable(champion_genome),
            "strategy_definition": champion_genome.to_strategy_definition(),
        },
        "generations": generation_log,
    }

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the evolution script.

    Args:
        argv: Argument list to parse.  Defaults to ``sys.argv[1:]``.

    Returns:
        Parsed :class:`argparse.Namespace`.
    """
    parser = argparse.ArgumentParser(
        prog="python -m agent.strategies.evolutionary.evolve",
        description="Run N generations of genetic algorithm strategy optimisation.",
    )
    parser.add_argument(
        "--generations",
        type=int,
        default=None,
        metavar="N",
        help="Override EVO_GENERATIONS (default: 30).",
    )
    parser.add_argument(
        "--pop-size",
        dest="pop_size",
        type=int,
        default=None,
        metavar="N",
        help="Override EVO_POPULATION_SIZE (default: 12).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Override EVO_SEED for reproducible runs (default: 42).",
    )
    parser.add_argument(
        "--elite-pct",
        dest="elite_pct",
        type=float,
        default=None,
        metavar="F",
        help="Override EVO_ELITE_PCT fraction (default: 0.2).",
    )
    parser.add_argument(
        "--mutation-rate",
        dest="mutation_rate",
        type=float,
        default=None,
        metavar="F",
        help="Override EVO_MUTATION_RATE (default: 0.1).",
    )
    parser.add_argument(
        "--mutation-strength",
        dest="mutation_strength",
        type=float,
        default=None,
        metavar="F",
        help="Override EVO_MUTATION_STRENGTH (default: 0.1).",
    )
    parser.add_argument(
        "--battle-preset",
        dest="battle_preset",
        type=str,
        default=None,
        metavar="PRESET",
        help="Override EVO_BATTLE_PRESET (default: historical_week).",
    )
    parser.add_argument(
        "--convergence-threshold",
        dest="convergence_threshold",
        type=int,
        default=None,
        metavar="N",
        help="Override EVO_CONVERGENCE_THRESHOLD (default: 5).",
    )
    parser.add_argument(
        "--fitness-fn",
        dest="fitness_fn",
        type=str,
        default=None,
        metavar="FN",
        choices=["sharpe_minus_drawdown", "sharpe_only", "roi_only"],
        help="Override EVO_FITNESS_FN (default: sharpe_minus_drawdown).",
    )
    return parser.parse_args(argv)


def _configure_logging() -> None:
    """Configure structlog with ISO timestamps and JSON output.

    Mirrors the logging setup used by the main agent entry point so that
    evolution log output is consistent with the rest of the platform.
    """
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(message)s",
    )


async def _main(argv: list[str] | None = None) -> int:
    """Async entry point: parse args, build config, run evolution, save results.

    Args:
        argv: Optional argument list for testing; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code: 0 on success, 1 on fatal error.
    """
    _configure_logging()
    args = _parse_args(argv)

    # Build config from environment then apply CLI overrides.
    try:
        cfg = EvolutionConfig()
    except Exception as exc:  # noqa: BLE001
        logger.error("evolve.config_load_failed", error=str(exc))
        print(f"[error] Failed to load EvolutionConfig: {exc}", file=sys.stderr)
        return 1

    # Apply CLI overrides via model_copy so Pydantic validators still run.
    overrides: dict[str, Any] = {}
    if args.generations is not None:
        overrides["generations"] = args.generations
    if args.pop_size is not None:
        overrides["population_size"] = args.pop_size
    if args.seed is not None:
        overrides["seed"] = args.seed
    if args.elite_pct is not None:
        overrides["elite_pct"] = args.elite_pct
    if args.mutation_rate is not None:
        overrides["mutation_rate"] = args.mutation_rate
    if args.mutation_strength is not None:
        overrides["mutation_strength"] = args.mutation_strength
    if args.battle_preset is not None:
        overrides["battle_preset"] = args.battle_preset
    if args.convergence_threshold is not None:
        overrides["convergence_threshold"] = args.convergence_threshold
    if args.fitness_fn is not None:
        overrides["fitness_fn"] = args.fitness_fn
    if overrides:
        cfg = cfg.model_copy(update=overrides)

    logger.info(
        "evolve.start",
        generations=cfg.generations,
        population_size=cfg.population_size,
        seed=cfg.seed,
        battle_preset=cfg.battle_preset,
        fitness_fn=cfg.fitness_fn,
        historical_start=str(cfg.historical_start),
        historical_end=str(cfg.historical_end),
    )

    print(  # noqa: T201
        f"[evolution] starting: {cfg.generations} gen × {cfg.population_size} pop | "
        f"seed={cfg.seed} | preset={cfg.battle_preset} | "
        f"window={cfg.historical_start}/{cfg.historical_end}"
    )

    try:
        summary = await run_evolution(cfg)
    except Exception as exc:  # noqa: BLE001
        logger.error("evolve.fatal_error", error=str(exc), exc_info=True)
        print(f"[error] Evolution failed: {exc}", file=sys.stderr)
        return 1

    # Persist results to disk.
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _save_json(_EVOLUTION_LOG_PATH, summary)

    champion_record: dict[str, Any] = {
        "saved_at": datetime.now(UTC).isoformat(),
        "champion_generation": summary["champion"]["generation"],
        "champion_fitness": summary["champion"]["fitness"],
        "genome": summary["champion"]["genome"],
        "strategy_definition": summary["champion"]["strategy_definition"],
    }
    _save_json(_CHAMPION_PATH, champion_record)

    gens_run: int = summary["config"]["generations_run"]
    champ_fitness: float = summary["champion"]["fitness"]
    champ_gen: int = summary["champion"]["generation"]

    print(  # noqa: T201
        f"\n[evolution] complete — {gens_run} generations run\n"
        f"  champion: gen {champ_gen}, fitness {champ_fitness:.4f}\n"
        f"  pairs:    {summary['champion']['genome']['pairs']}\n"
        f"  rsi:      oversold={summary['champion']['genome']['rsi_oversold']:.1f}, "
        f"overbought={summary['champion']['genome']['rsi_overbought']:.1f}\n"
        f"  macd:     fast={summary['champion']['genome']['macd_fast']}, "
        f"slow={summary['champion']['genome']['macd_slow']}\n"
        f"  stop/tp:  stop={summary['champion']['genome']['stop_loss_pct']:.3f}, "
        f"tp={summary['champion']['genome']['take_profit_pct']:.3f}\n"
        f"  results:  {_EVOLUTION_LOG_PATH}\n"
        f"  champion: {_CHAMPION_PATH}"
    )

    logger.info(
        "evolve.complete",
        generations_run=gens_run,
        champion_fitness=champ_fitness,
        champion_generation=champ_gen,
        log_path=str(_EVOLUTION_LOG_PATH),
        champion_path=str(_CHAMPION_PATH),
    )

    return 0


def main(argv: list[str] | None = None) -> None:
    """Synchronous entry point used by ``python -m agent.strategies.evolutionary.evolve``.

    Args:
        argv: Optional argument list; defaults to ``sys.argv[1:]``.
    """
    exit_code = asyncio.run(_main(argv))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
