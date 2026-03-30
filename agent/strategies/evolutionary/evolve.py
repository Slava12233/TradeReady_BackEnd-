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
   c. Runs an **in-sample** historical battle (first 70 % of the window by
      default) and extracts per-agent metrics.
   d. Runs an **out-of-sample (OOS)** historical battle on the held-out 30 %
      of the window and extracts per-agent OOS Sharpe ratios.
   e. Computes composite fitness using the 5-factor formula::

          fitness = (
              0.35 * sharpe_ratio
              + 0.25 * profit_factor
              - 0.20 * max_drawdown_pct
              + 0.10 * win_rate
              + 0.10 * oos_sharpe_ratio
          )

   f. Logs gen #, best/avg/worst fitness, OOS Sharpe, and the champion's key params.
   g. Checks convergence: stops early if no improvement for
      ``config.convergence_threshold`` consecutive generations.
   h. Saves the champion genome as a new strategy version via the REST API.
   i. Evolves the population → next generation.
7. Writes ``results/evolution_log.json`` and ``results/champion.json`` to disk.

Battle failures are caught per-generation: the generation is skipped (fitness
scores default to -999), the error is logged, and the loop continues.  This
prevents a single HTTP error from aborting a multi-hour optimisation run.

Fitness functions:

- ``composite`` (default) — 5-factor OOS-weighted formula above.
- ``sharpe_minus_drawdown`` (legacy) — ``sharpe - 0.5 * max_drawdown``.
- ``sharpe_only`` — raw Sharpe ratio.
- ``roi_only`` — return-on-investment percentage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from agent.config import AgentConfig
from agent.strategies.evolutionary.battle_runner import FAILURE_FITNESS, BattleRunner
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
# Composite fitness computation
# ---------------------------------------------------------------------------

# Weights for the 5-factor composite fitness formula.  These are intentional
# hyperparameters reflecting the following design decisions:
#   - Sharpe (0.35): Primary risk-adjusted return signal — the dominant term.
#   - Profit factor (0.25): Penalises strategies that win rarely on large losses.
#   - Drawdown (-0.20): Negative weight: higher drawdown is worse.  Capped
#     at 0.20 so it does not overwhelm Sharpe on high-volatility strategies.
#   - Win rate (0.10): Secondary quality signal; avoids strategies with
#     excessive loss count even if PnL is positive.
#   - OOS Sharpe (0.10): Out-of-sample penalty — rewards genomes that generalise
#     beyond the in-sample period and discourages overfitting.
_FITNESS_WEIGHT_SHARPE: float = 0.35
_FITNESS_WEIGHT_PROFIT_FACTOR: float = 0.25
_FITNESS_WEIGHT_DRAWDOWN: float = -0.20
_FITNESS_WEIGHT_WIN_RATE: float = 0.10
_FITNESS_WEIGHT_OOS_SHARPE: float = 0.10

# Fallback values used when a metric is unavailable.  These are intentionally
# neutral (0.0) so the missing term does not skew the score in either direction.
_FALLBACK_SHARPE: float = 0.0
_FALLBACK_PROFIT_FACTOR: float = 1.0  # neutral: gross profit == gross loss
_FALLBACK_DRAWDOWN: float = 0.0
_FALLBACK_WIN_RATE: float = 0.5  # neutral: 50/50 win rate
_FALLBACK_OOS_SHARPE: float = 0.0


def compute_composite_fitness(
    sharpe: float | None,
    profit_factor: float | None,
    max_drawdown_pct: float | None,
    win_rate: float | None,
    oos_sharpe: float | None,
) -> float:
    """Compute the 5-factor composite fitness for a single genome.

    Missing metrics (``None``) are replaced by neutral fallback values rather
    than defaulting to ``FAILURE_FITNESS``, so strategies that do not trade at
    all can still receive a partial score.  The caller is responsible for
    assigning ``FAILURE_FITNESS`` when the agent produced no results at all.

    The formula::

        fitness = (
            0.35 * sharpe_ratio
            + 0.25 * profit_factor_clamped
            - 0.20 * max_drawdown_pct
            + 0.10 * win_rate
            + 0.10 * oos_sharpe_ratio
        )

    ``profit_factor`` is clamped to ``[0, 5]`` to prevent single lucky trades
    from dominating the score.

    Args:
        sharpe: In-sample Sharpe ratio; ``None`` if unavailable.
        profit_factor: Gross profit / gross loss; ``None`` if no trades.
        max_drawdown_pct: Maximum drawdown as a percentage [0, 100]; ``None``
            if unavailable.
        win_rate: Fraction of winning trades [0, 1]; ``None`` if no trades.
        oos_sharpe: Out-of-sample Sharpe ratio; ``None`` if OOS battle failed.

    Returns:
        Scalar composite fitness value.  Higher is better.
    """
    s = sharpe if sharpe is not None else _FALLBACK_SHARPE
    # Clamp profit factor: values > 5 are usually due to very few lucky trades
    # and should not dominate the score.
    pf_raw = profit_factor if profit_factor is not None else _FALLBACK_PROFIT_FACTOR
    pf = max(0.0, min(5.0, pf_raw))
    dd = max_drawdown_pct if max_drawdown_pct is not None else _FALLBACK_DRAWDOWN
    wr = win_rate if win_rate is not None else _FALLBACK_WIN_RATE
    oos = oos_sharpe if oos_sharpe is not None else _FALLBACK_OOS_SHARPE

    return (
        _FITNESS_WEIGHT_SHARPE * s
        + _FITNESS_WEIGHT_PROFIT_FACTOR * pf
        + _FITNESS_WEIGHT_DRAWDOWN * dd
        + _FITNESS_WEIGHT_WIN_RATE * wr
        + _FITNESS_WEIGHT_OOS_SHARPE * oos
    )


def _compute_fitness(
    agent_ids: list[str],
    is_metrics: dict[str, dict[str, float | None]],
    oos_sharpe_map: dict[str, float | None],
    fitness_fn: str,
) -> list[float]:
    """Map per-agent metrics to an ordered fitness list aligned with ``agent_ids``.

    Supports four fitness function modes:

    - ``composite`` (default): 5-factor formula including OOS Sharpe.
    - ``sharpe_minus_drawdown`` (legacy): ``sharpe - 0.5 * drawdown``.
    - ``sharpe_only``: In-sample Sharpe ratio.
    - ``roi_only``: Return-on-investment percentage.

    Args:
        agent_ids: Ordered list of platform agent IDs matching the population.
        is_metrics: In-sample metrics per agent from
            :meth:`~BattleRunner.get_detailed_metrics`.
        oos_sharpe_map: OOS Sharpe per agent; ``None`` values indicate OOS
            battle failed for that agent.
        fitness_fn: Fitness function identifier from :class:`EvolutionConfig`.

    Returns:
        Ordered list of float fitness values, one per genome.
    """
    scores: list[float] = []

    for aid in agent_ids:
        m = is_metrics.get(aid)
        if m is None:
            scores.append(FAILURE_FITNESS)
            continue

        sharpe = m.get("sharpe_ratio")
        drawdown = m.get("max_drawdown_pct")
        profit_factor = m.get("profit_factor")
        win_rate = m.get("win_rate")
        roi = m.get("roi_pct")
        oos_sharpe = oos_sharpe_map.get(aid)

        if fitness_fn == "composite":
            scores.append(
                compute_composite_fitness(
                    sharpe=sharpe,
                    profit_factor=profit_factor,
                    max_drawdown_pct=drawdown,
                    win_rate=win_rate,
                    oos_sharpe=oos_sharpe,
                )
            )
        elif fitness_fn == "sharpe_minus_drawdown":
            if sharpe is None or drawdown is None:
                scores.append(float(roi) if roi is not None else FAILURE_FITNESS)
            else:
                scores.append(float(sharpe) - 0.5 * float(drawdown))
        elif fitness_fn == "sharpe_only":
            scores.append(float(sharpe) if sharpe is not None else FAILURE_FITNESS)
        elif fitness_fn == "roi_only":
            scores.append(float(roi) if roi is not None else FAILURE_FITNESS)
        else:
            # Unreachable: config validator rejects unknown values.
            scores.append(FAILURE_FITNESS)

    return scores


# ---------------------------------------------------------------------------
# OOS Sharpe extraction helpers
# ---------------------------------------------------------------------------

async def _run_oos_battle(
    runner: BattleRunner,
    cfg: EvolutionConfig,
    gen_number: int,
) -> dict[str, float | None]:
    """Run an OOS battle and extract per-agent Sharpe ratios.

    This battle uses the held-out period (last ``oos_split_ratio`` fraction of
    the total window) so fitness is penalised for strategies that overfit the
    in-sample window.

    Args:
        runner: Configured :class:`BattleRunner` with agents already provisioned
            and strategies already assigned for the current generation.
        cfg: Evolution config supplying the OOS window dates.
        gen_number: 1-based generation number (for logging and battle naming).

    Returns:
        Dict mapping agent_id → OOS Sharpe ratio (or ``None`` if unavailable).
        On battle failure, returns an all-``None`` dict for every agent.
    """
    null_map: dict[str, float | None] = {aid: None for aid in runner.agent_ids}
    oos_window = cfg.oos_window

    try:
        # Agents are already provisioned and have their strategies assigned.
        # We reset balances so the OOS battle starts from a clean slate.
        await runner.reset_agents()
        oos_battle_id = await runner.run_battle(
            preset=cfg.battle_preset,
            historical_window=oos_window,
        )
        oos_metrics = await runner.get_detailed_metrics(oos_battle_id)
        await runner.cleanup(oos_battle_id)

        sharpe_map: dict[str, float | None] = {
            aid: m.get("sharpe_ratio") for aid, m in oos_metrics.items()
        }
        logger.info(
            "agent.strategy.evolutionary.evolve.oos_battle_complete",
            gen=gen_number,
            oos_start=oos_window[0],
            oos_end=oos_window[1],
            sharpes={aid: (round(v, 4) if v is not None else None) for aid, v in sharpe_map.items()},
        )
        return sharpe_map

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agent.strategy.evolutionary.evolve.oos_battle_failed",
            gen=gen_number,
            error=str(exc),
        )
        return null_map


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
    logger.info("agent.strategy.evolutionary.evolve.saved_file", path=str(path))


async def _save_champion_strategy(
    rest_client: PlatformRESTClient,
    champion: StrategyGenome,
    generation: int,
    fitness: float,
    *,
    strategy_id: str | None = None,
) -> str | None:
    """Create a platform strategy version for the champion genome.

    On the first call (``strategy_id=None``) a new strategy is created.
    On subsequent calls a new version is appended to the same strategy.
    The caller is responsible for threading the returned strategy ID back
    into subsequent calls so no mutable module-level state is required.

    Args:
        rest_client: API-key authenticated REST client.
        champion: The best genome found so far.
        generation: Current generation index (0-based) for naming.
        fitness: Best fitness score, included in change notes.
        strategy_id: The platform strategy ID from a previous call within
            this run, or ``None`` to create a new strategy.

    Returns:
        The platform strategy ID string on success, ``None`` on failure.
    """
    definition = champion.to_strategy_definition()
    name = f"evo-champion-gen{generation}"
    description = (
        f"Evolutionary champion — generation {generation}, "
        f"fitness {fitness:.4f}"
    )

    try:
        if strategy_id is None:
            result = await rest_client.create_strategy(
                name=name,
                description=description,
                definition=definition,
            )
            if "error" in result:
                logger.warning(
                    "agent.strategy.evolutionary.evolve.champion_strategy_save_failed",
                    generation=generation,
                    error=result["error"],
                )
                return None
            strategy_id = str(result.get("strategy_id", ""))
            logger.info(
                "agent.strategy.evolutionary.evolve.champion_strategy_created",
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
                    "agent.strategy.evolutionary.evolve.champion_version_save_failed",
                    strategy_id=strategy_id,
                    generation=generation,
                    error=result["error"],
                )
                # Non-fatal: return the existing strategy_id anyway.
            else:
                logger.info(
                    "agent.strategy.evolutionary.evolve.champion_version_created",
                    strategy_id=strategy_id,
                    generation=generation,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agent.strategy.evolutionary.evolve.champion_strategy_exception",
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

    The detector tracks the composite best fitness (which includes OOS Sharpe)
    rather than the raw in-sample metric, ensuring convergence is measured
    against the full anti-overfit objective.

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
        # Track best OOS Sharpe separately for diagnostic logging.
        self._best_oos_sharpe: float | None = None

    def update(self, best_fitness: float, best_oos_sharpe: float | None = None) -> None:
        """Register the best fitness for the current generation.

        Args:
            best_fitness: The highest composite fitness value observed this
                generation (includes OOS term).
            best_oos_sharpe: The OOS Sharpe of the best genome this generation.
                Stored for diagnostic purposes only; does not affect convergence
                logic.
        """
        if best_fitness - self._best >= self._min_improvement:
            self._best = best_fitness
            self._stale_gens = 0
        else:
            self._stale_gens += 1

        if best_oos_sharpe is not None:
            self._best_oos_sharpe = best_oos_sharpe

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

    @property
    def best_oos_sharpe(self) -> float | None:
        """Best OOS Sharpe seen so far across all generations.

        Returns:
            OOS Sharpe of the best composite-fitness genome, or ``None`` if
            OOS data has not been recorded yet.
        """
        return self._best_oos_sharpe


# ---------------------------------------------------------------------------
# Main evolution loop
# ---------------------------------------------------------------------------

async def run_evolution(cfg: EvolutionConfig) -> dict[str, Any]:
    """Execute the full genetic algorithm loop.

    Initialises the population, provisions battle agents, then iterates for
    up to ``cfg.generations`` generations.  Each generation runs two historical
    battles — one in-sample (first ``1 - oos_split_ratio`` fraction of the
    window) and one out-of-sample (last ``oos_split_ratio`` fraction) — then
    combines the results into a composite fitness score.

    Args:
        cfg: Fully-resolved :class:`EvolutionConfig` with all hyperparameters.

    Returns:
        A JSON-serialisable summary dict containing the champion genome,
        per-generation stats (including OOS Sharpe), and final metadata.
        This dict is written to ``results/evolution_log.json`` by the caller.
    """
    # Local variable tracks the platform strategy ID across generations
    # within this run.  Using a local variable (rather than a module-level
    # global) prevents cross-run state contamination when multiple runs
    # execute within the same Python process (e.g. in tests or the CLI
    # walk-forward loop).
    _run_champion_strategy_id: str | None = None

    agent_cfg = AgentConfig()  # reads agent/.env

    # Log the window split for operator visibility.
    is_start, split, oos_end = cfg.is_split
    logger.info(
        "agent.strategy.evolutionary.evolve.window_split",
        is_start=is_start,
        split_point=split,
        oos_end=oos_end,
        oos_split_ratio=cfg.oos_split_ratio,
        fitness_fn=cfg.fitness_fn,
    )

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
    champion_oos_sharpe: float | None = None

    async with PlatformRESTClient(agent_cfg) as rest_client:
        runner = await BattleRunner.create(agent_cfg, rest_client)
        async with runner:
            # One-time provisioning of battle agents.
            await runner.setup_agents(cfg.population_size)
            logger.info(
                "agent.strategy.evolutionary.evolve.agents_provisioned",
                count=cfg.population_size,
            )

            for gen_idx in range(cfg.generations):
                gen_number = gen_idx + 1  # 1-based for display
                log = logger.bind(gen=gen_number, total=cfg.generations)

                is_battle_id: str | None = None
                fitness_scores: list[float] = [FAILURE_FITNESS] * cfg.population_size
                oos_sharpe_map: dict[str, float | None] = {
                    aid: None for aid in runner.agent_ids
                }
                is_metrics: dict[str, dict[str, float | None]] = {}

                try:
                    # Step a: Reset agent balances for the in-sample battle.
                    await runner.reset_agents()

                    # Step b: Assign current population genomes as strategies.
                    await runner.assign_strategies(population.genomes)

                    # Step c: Run the in-sample historical battle.
                    is_window = cfg.in_sample_window
                    is_battle_id = await runner.run_battle(
                        preset=cfg.battle_preset,
                        historical_window=is_window,
                    )
                    is_metrics = await runner.get_detailed_metrics(is_battle_id)
                    await runner.cleanup(is_battle_id)

                    # Step d: Run the OOS battle on the held-out period.
                    # Strategies are already assigned — we only reset balances.
                    if cfg.fitness_fn == "composite":
                        oos_sharpe_map = await _run_oos_battle(runner, cfg, gen_number)
                    # For legacy fitness functions, oos_sharpe_map stays all-None.

                    # Step e: Compute fitness using the configured formula.
                    fitness_scores = _compute_fitness(
                        runner.agent_ids,
                        is_metrics,
                        oos_sharpe_map,
                        cfg.fitness_fn,
                    )

                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "agent.strategy.evolutionary.evolve.generation_failed",
                        error=str(exc),
                        is_battle_id=is_battle_id,
                    )
                    # Skip evolution for this generation; fitness stays at -999.

                # Step f: Compute stats and log.
                stats: PopulationStats = population.stats(fitness_scores)
                best_genome: StrategyGenome = population.best(fitness_scores)

                # Find the OOS Sharpe for the best-fitness genome this generation.
                best_idx = fitness_scores.index(stats.best) if stats.best != FAILURE_FITNESS else 0
                best_agent_id = runner.agent_ids[best_idx] if runner.agent_ids else None
                best_oos_sharpe: float | None = (
                    oos_sharpe_map.get(best_agent_id) if best_agent_id else None
                )

                log.info(
                    "agent.strategy.evolutionary.evolve.generation_stats",
                    best=round(stats.best, 4),
                    avg=round(stats.mean, 4),
                    worst=round(stats.worst, 4),
                    stale=convergence.stale_generations,
                    best_oos_sharpe=(
                        round(best_oos_sharpe, 4) if best_oos_sharpe is not None else None
                    ),
                )

                # Human-readable progress line.
                oos_str = (
                    f" | oos_sharpe: {best_oos_sharpe:.2f}"
                    if best_oos_sharpe is not None
                    else ""
                )
                print(  # noqa: T201
                    f"gen {gen_number}/{cfg.generations} | "
                    f"best: {stats.best:.2f} | "
                    f"avg: {stats.mean:.2f} | "
                    f"worst: {stats.worst:.2f}"
                    + oos_str
                )

                # Update overall champion.
                if stats.best > champion_fitness:
                    champion_genome = best_genome
                    champion_fitness = stats.best
                    champion_generation = gen_idx
                    champion_oos_sharpe = best_oos_sharpe

                # Step g: Check convergence before evolving (tracks composite fitness).
                convergence.update(stats.best, best_oos_sharpe)

                # Step h: Save champion genome as a new strategy version.
                # Thread the run-local strategy ID through each call so the
                # same strategy accumulates new versions rather than spawning
                # a fresh strategy every generation.
                saved_id = await _save_champion_strategy(
                    rest_client=rest_client,
                    champion=champion_genome,
                    generation=gen_idx,
                    fitness=champion_fitness,
                    strategy_id=_run_champion_strategy_id,
                )
                if saved_id is not None:
                    _run_champion_strategy_id = saved_id

                # Record generation entry for the evolution log.
                gen_record: dict[str, Any] = {
                    "generation": gen_number,
                    "best_fitness": round(stats.best, 6),
                    "avg_fitness": round(stats.mean, 6),
                    "worst_fitness": round(stats.worst, 6),
                    "std_fitness": round(stats.std, 6),
                    "stale_generations": convergence.stale_generations,
                    "is_battle_id": is_battle_id,
                    "best_oos_sharpe": (
                        round(best_oos_sharpe, 6) if best_oos_sharpe is not None else None
                    ),
                    "champion_params": _genome_to_loggable(best_genome),
                }
                generation_log.append(gen_record)

                if convergence.converged:
                    log.info(
                        "agent.strategy.evolutionary.evolve.converged",
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

                # Step i: Evolve population → next generation (skip after last gen).
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
            "oos_split_ratio": cfg.oos_split_ratio,
            "in_sample_window": list(cfg.in_sample_window),
            "oos_window": list(cfg.oos_window),
            "convergence_threshold": cfg.convergence_threshold,
            "fitness_fn": cfg.fitness_fn,
            "seed": cfg.seed,
        },
        "champion": {
            "generation": champion_generation + 1,  # 1-based
            "fitness": round(champion_fitness, 6),
            "oos_sharpe": (
                round(champion_oos_sharpe, 6) if champion_oos_sharpe is not None else None
            ),
            "genome": _genome_to_loggable(champion_genome),
            "strategy_definition": champion_genome.to_strategy_definition(),
        },
        "generations": generation_log,
    }

    return summary


# ---------------------------------------------------------------------------
# Walk-forward helper for the evolutionary strategy
# ---------------------------------------------------------------------------


async def walk_forward_evolve(
    cfg: EvolutionConfig | None = None,
    data_start: str | None = None,
    data_end: str | None = None,
    train_months: int = 6,
    oos_months: int = 1,
) -> "WalkForwardResult":  # type: ignore[name-defined]
    """Run rolling walk-forward validation for the genetic algorithm strategy.

    For each rolling window the full GA evolution loop runs on the in-sample
    period, then the champion genome is evaluated on the immediately following
    OOS window.  Walk-Forward Efficiency (WFE) must exceed 50 % for the
    strategy to be considered deployable.

    This is a convenience wrapper around
    :func:`~agent.strategies.walk_forward.walk_forward_evolutionary` that
    defaults to reading ``EvolutionConfig`` from environment / ``agent/.env``.

    Args:
        cfg: Optional :class:`EvolutionConfig` instance.  When ``None`` a fresh
            instance is loaded from the environment.
        data_start: ISO-8601 UTC start of the full data range.  Defaults to
            ``cfg.historical_start`` formatted as ISO-8601.
        data_end: ISO-8601 UTC end of the full data range.  Defaults to
            ``cfg.historical_end`` formatted as ISO-8601.
        train_months: Calendar months in each training window.  Default 6.
        oos_months: Calendar months in each OOS window.  Default 1.

    Returns:
        :class:`~agent.strategies.walk_forward.WalkForwardResult` with
        per-window composite fitness metrics, WFE, and a deployability flag.

    Side effects:
        Writes
        ``agent/strategies/walk_forward_results/evolutionary_wf_report.json``
        with the full per-window breakdown and summary.
    """
    from agent.strategies.walk_forward import (  # noqa: PLC0415
        WalkForwardConfig,
        WalkForwardResult,
        walk_forward_evolutionary,
    )

    if cfg is None:
        cfg = EvolutionConfig()

    wf_config = WalkForwardConfig(
        data_start=data_start or f"{cfg.historical_start.isoformat()}T00:00:00Z",
        data_end=data_end or f"{cfg.historical_end.isoformat()}T00:00:00Z",
        train_months=train_months,
        oos_months=oos_months,
    )

    logger.info(
        "agent.strategy.evolutionary.evolve.walk_forward.start",
        data_start=wf_config.data_start,
        data_end=wf_config.data_end,
        train_months=train_months,
        oos_months=oos_months,
    )

    result: WalkForwardResult = await walk_forward_evolutionary(
        evo_config=cfg,
        wf_config=wf_config,
    )

    logger.info(
        "agent.strategy.evolutionary.evolve.walk_forward.complete",
        wfe=result.walk_forward_efficiency,
        is_deployable=result.is_deployable,
        successful_windows=result.successful_windows,
        total_windows=result.total_windows,
    )

    if result.overfit_warning:
        logger.warning(
            "agent.strategy.evolutionary.evolve.walk_forward.overfit_warning",
            wfe=result.walk_forward_efficiency,
            threshold=result.wfe_threshold,
            message="WFE below threshold — strategy likely overfit. Do NOT deploy.",
        )

    return result


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
        choices=["composite", "sharpe_minus_drawdown", "sharpe_only", "roi_only"],
        help="Override EVO_FITNESS_FN (default: composite).",
    )
    parser.add_argument(
        "--oos-split-ratio",
        dest="oos_split_ratio",
        type=float,
        default=None,
        metavar="F",
        help=(
            "Override EVO_OOS_SPLIT_RATIO (default: 0.30).  "
            "Fraction of the battle window held out for OOS evaluation."
        ),
    )
    return parser.parse_args(argv)


def _configure_logging() -> None:
    """Configure structlog with ISO timestamps and JSON output.

    Mirrors the logging setup used by the main agent entry point so that
    evolution log output is consistent with the rest of the platform.
    """
    from agent.logging import configure_agent_logging  # noqa: PLC0415

    configure_agent_logging()


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
        logger.error("agent.strategy.evolutionary.evolve.config_load_failed", error=str(exc))
        print(f"[error] Failed to load EvolutionConfig: {exc}", file=sys.stderr)  # noqa: T201
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
    if args.oos_split_ratio is not None:
        overrides["oos_split_ratio"] = args.oos_split_ratio
    if overrides:
        cfg = cfg.model_copy(update=overrides)

    is_start, split, oos_end = cfg.is_split
    logger.info(
        "agent.strategy.evolutionary.evolve.start",
        generations=cfg.generations,
        population_size=cfg.population_size,
        seed=cfg.seed,
        battle_preset=cfg.battle_preset,
        fitness_fn=cfg.fitness_fn,
        historical_start=str(cfg.historical_start),
        historical_end=str(cfg.historical_end),
        oos_split_ratio=cfg.oos_split_ratio,
        is_window=f"{is_start} → {split}",
        oos_window=f"{split} → {oos_end}",
    )

    print(  # noqa: T201
        f"[evolution] starting: {cfg.generations} gen × {cfg.population_size} pop | "
        f"seed={cfg.seed} | preset={cfg.battle_preset} | fn={cfg.fitness_fn}\n"
        f"  IS window:  {is_start} → {split}\n"
        f"  OOS window: {split} → {oos_end} (held-out {cfg.oos_split_ratio:.0%})"
    )

    try:
        summary = await run_evolution(cfg)
    except Exception as exc:  # noqa: BLE001
        logger.error("agent.strategy.evolutionary.evolve.fatal_error", error=str(exc), exc_info=True)
        print(f"[error] Evolution failed: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    # Persist results to disk.
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _save_json(_EVOLUTION_LOG_PATH, summary)

    champion_record: dict[str, Any] = {
        "saved_at": datetime.now(UTC).isoformat(),
        "champion_generation": summary["champion"]["generation"],
        "champion_fitness": summary["champion"]["fitness"],
        "champion_oos_sharpe": summary["champion"]["oos_sharpe"],
        "genome": summary["champion"]["genome"],
        "strategy_definition": summary["champion"]["strategy_definition"],
    }
    _save_json(_CHAMPION_PATH, champion_record)

    gens_run: int = summary["config"]["generations_run"]
    champ_fitness: float = summary["champion"]["fitness"]
    champ_gen: int = summary["champion"]["generation"]
    champ_oos: float | None = summary["champion"]["oos_sharpe"]

    oos_display = f"{champ_oos:.4f}" if champ_oos is not None else "N/A"
    print(  # noqa: T201
        f"\n[evolution] complete — {gens_run} generations run\n"
        f"  champion:   gen {champ_gen}, fitness {champ_fitness:.4f}"
        f" (oos_sharpe={oos_display})\n"
        f"  pairs:      {summary['champion']['genome']['pairs']}\n"
        f"  rsi:        oversold={summary['champion']['genome']['rsi_oversold']:.1f}, "
        f"overbought={summary['champion']['genome']['rsi_overbought']:.1f}\n"
        f"  macd:       fast={summary['champion']['genome']['macd_fast']}, "
        f"slow={summary['champion']['genome']['macd_slow']}\n"
        f"  stop/tp:    stop={summary['champion']['genome']['stop_loss_pct']:.3f}, "
        f"tp={summary['champion']['genome']['take_profit_pct']:.3f}\n"
        f"  results:    {_EVOLUTION_LOG_PATH}\n"
        f"  champion:   {_CHAMPION_PATH}"
    )

    logger.info(
        "agent.strategy.evolutionary.evolve.complete",
        generations_run=gens_run,
        champion_fitness=champ_fitness,
        champion_generation=champ_gen,
        champion_oos_sharpe=champ_oos,
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
