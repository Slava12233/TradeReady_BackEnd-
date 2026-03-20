"""Evolution analysis and reporting — post-run analysis of genetic algorithm results.

Loads the ``evolution_log.json`` produced by :mod:`agent.strategies.evolutionary.evolve`
and computes:

- Fitness curve (best / avg / worst per generation).
- Parameter convergence (standard deviation in first vs last generation).
- Champion strategy description in human-readable prose.
- Optional baseline comparison via a platform battle.
- Optional trade behaviour analysis via the battle replay endpoint.

CLI entry point::

    python -m agent.strategies.evolutionary.analyze --log-path results/evolution_log.json

Offline analysis (no platform connection required) produces everything except the
``baseline_comparison`` and ``trade_behavior`` sections.  Pass ``--no-baseline`` to
skip the live battle entirely.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PACKAGE_DIR: Path = Path(__file__).parent
_DEFAULT_LOG_PATH: Path = _PACKAGE_DIR / "results" / "evolution_log.json"
_REPORTS_DIR: Path = _PACKAGE_DIR.parent.parent / "reports"

# ---------------------------------------------------------------------------
# Parameter groupings (mirrors genome.py SCALAR_BOUNDS / INT_BOUNDS)
# ---------------------------------------------------------------------------

_SCALAR_PARAMS: list[str] = [
    "rsi_oversold",
    "rsi_overbought",
    "adx_threshold",
    "stop_loss_pct",
    "take_profit_pct",
    "trailing_stop_pct",
    "position_size_pct",
]

_INT_PARAMS: list[str] = [
    "macd_fast",
    "macd_slow",
    "max_hold_candles",
    "max_positions",
]

_ALL_NUMERIC_PARAMS: list[str] = _SCALAR_PARAMS + _INT_PARAMS

# Threshold below which a parameter is considered "converged" relative to the
# first generation's std.  A reduction of 50 % or more in std signals convergence.
_CONVERGENCE_REDUCTION_THRESHOLD: float = 0.50

# ---------------------------------------------------------------------------
# Pydantic output model
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field  # noqa: E402  (after stdlib imports)


class GenerationStats(BaseModel):
    """Fitness statistics for a single generation.

    Attributes:
        generation: 1-based generation index.
        best_fitness: Highest individual fitness in the generation.
        avg_fitness: Mean fitness across all individuals.
        worst_fitness: Lowest individual fitness in the generation.
        std_fitness: Standard deviation of fitness scores.
    """

    generation: int
    best_fitness: float
    avg_fitness: float
    worst_fitness: float
    std_fitness: float


class ParameterConvergence(BaseModel):
    """Convergence analysis for a single genome parameter.

    Attributes:
        param: Parameter name.
        first_gen_std: Standard deviation in the first generation.
        last_gen_std: Standard deviation in the final generation.
        reduction_pct: Percentage reduction in std from first to last generation.
            Positive means the population converged (std shrank).
        converged: True when std reduced by at least
            ``_CONVERGENCE_REDUCTION_THRESHOLD`` (50 %).
    """

    param: str
    first_gen_std: float
    last_gen_std: float
    reduction_pct: float
    converged: bool


class EvolutionReport(BaseModel):
    """Full post-evolution analysis report.

    Attributes:
        timestamp: ISO-8601 UTC timestamp when the report was generated.
        config_snapshot: Subset of the evolution run configuration captured
            directly from the evolution log.
        fitness_curve: Per-generation fitness statistics (best / avg / worst / std).
        convergence: Parameter-level convergence analysis keyed by parameter name.
        champion: Champion genome parameters and human-readable description.
        baseline_comparison: Comparison metrics from champion vs random baseline
            battle.  ``None`` when the comparison was skipped or failed.
        trade_behavior: Trade pattern analysis extracted from the replay endpoint.
            ``None`` when the analysis was skipped or failed.
    """

    timestamp: str = Field(description="ISO-8601 UTC generation timestamp")
    config_snapshot: dict[str, Any] = Field(description="Subset of the evolution run config")
    fitness_curve: list[GenerationStats] = Field(description="Per-generation fitness stats")
    convergence: dict[str, ParameterConvergence] = Field(
        description="Parameter convergence keyed by param name"
    )
    champion: dict[str, Any] = Field(description="Champion genome params + description")
    baseline_comparison: dict[str, Any] | None = Field(
        default=None,
        description="Champion vs random baseline battle metrics (None when skipped)",
    )
    trade_behavior: dict[str, Any] | None = Field(
        default=None,
        description="Trade pattern analysis from battle replay (None when skipped)",
    )


# ---------------------------------------------------------------------------
# Core analyser class
# ---------------------------------------------------------------------------


class EvolutionAnalyzer:
    """Analyses the output of a completed genetic algorithm run.

    Args:
        log_data: Parsed evolution log dict as returned by
            :func:`load_log`.  Pass ``None`` to call :meth:`load_log` later.
    """

    def __init__(self, log_data: dict[str, Any] | None = None) -> None:
        self._log: dict[str, Any] = log_data or {}

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_log(self, path: str | Path) -> "EvolutionAnalyzer":
        """Parse the evolution log JSON file and store it internally.

        Args:
            path: Path to ``evolution_log.json``.

        Returns:
            Self, for method chaining.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file is not valid JSON or is missing required keys.
        """
        resolved = Path(path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Evolution log not found: {resolved}")

        try:
            raw = resolved.read_text(encoding="utf-8")
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Evolution log is not valid JSON: {exc}") from exc

        required_keys = {"generations", "champion", "config"}
        missing = required_keys - set(data.keys())
        if missing:
            raise ValueError(f"Evolution log is missing required keys: {missing}")

        self._log = data
        logger.info("analyze.log_loaded", path=str(resolved), generations=len(data["generations"]))
        return self

    # ------------------------------------------------------------------
    # Fitness curve
    # ------------------------------------------------------------------

    def fitness_curve(self) -> list[GenerationStats]:
        """Extract per-generation fitness statistics from the evolution log.

        Returns:
            Ordered list of :class:`GenerationStats` objects, one per generation.

        Raises:
            RuntimeError: If no log data has been loaded.
        """
        self._require_log()
        generations: list[dict[str, Any]] = self._log["generations"]
        result: list[GenerationStats] = []

        for gen in generations:
            result.append(
                GenerationStats(
                    generation=int(gen["generation"]),
                    best_fitness=float(gen.get("best_fitness", 0.0)),
                    avg_fitness=float(gen.get("avg_fitness", 0.0)),
                    worst_fitness=float(gen.get("worst_fitness", 0.0)),
                    std_fitness=float(gen.get("std_fitness", 0.0)),
                )
            )

        return result

    # ------------------------------------------------------------------
    # Parameter convergence
    # ------------------------------------------------------------------

    def parameter_convergence(self) -> dict[str, ParameterConvergence]:
        """Analyse which genome parameters stabilised vs stayed variable.

        Computes the standard deviation of each numeric parameter across the
        population in generation 1 and in the final generation, then computes
        the percentage reduction.  A parameter is considered *converged* when
        its std shrank by at least 50 %.

        Note: The evolution log records the ``champion_params`` for the *best*
        individual only, not the full population.  This method therefore computes
        the std of parameter values across *all generations* (using the per-generation
        best values) as a proxy for trajectory variability, and compares the
        first-half vs second-half variance to identify convergence trends.

        Returns:
            Dict mapping parameter name to :class:`ParameterConvergence`.

        Raises:
            RuntimeError: If no log data has been loaded.
        """
        self._require_log()
        generations: list[dict[str, Any]] = self._log["generations"]

        if not generations:
            return {}

        # Collect the champion parameter value for every generation.
        # Shape: {param_name: [val_gen1, val_gen2, ...]}
        param_series: dict[str, list[float]] = {p: [] for p in _ALL_NUMERIC_PARAMS}

        for gen in generations:
            params = gen.get("champion_params", {})
            for p in _ALL_NUMERIC_PARAMS:
                if p in params:
                    param_series[p].append(float(params[p]))

        result: dict[str, ParameterConvergence] = {}

        for param, values in param_series.items():
            if len(values) < 2:
                # Not enough data — report zeros and mark as unknown.
                result[param] = ParameterConvergence(
                    param=param,
                    first_gen_std=0.0,
                    last_gen_std=0.0,
                    reduction_pct=0.0,
                    converged=False,
                )
                continue

            # Split into first half / second half.
            mid = max(1, len(values) // 2)
            first_half = values[:mid]
            second_half = values[mid:]

            # Use population std (ddof=0) to avoid division error on small samples.
            first_std = float(statistics.pstdev(first_half)) if len(first_half) > 1 else 0.0
            last_std = float(statistics.pstdev(second_half)) if len(second_half) > 1 else 0.0

            if first_std == 0.0:
                # Parameter was constant throughout — fully converged.
                reduction_pct = 100.0
                converged = True
            else:
                reduction_pct = round((1.0 - last_std / first_std) * 100.0, 2)
                converged = reduction_pct >= (_CONVERGENCE_REDUCTION_THRESHOLD * 100.0)

            result[param] = ParameterConvergence(
                param=param,
                first_gen_std=round(first_std, 6),
                last_gen_std=round(last_std, 6),
                reduction_pct=reduction_pct,
                converged=converged,
            )

        return result

    # ------------------------------------------------------------------
    # Champion description
    # ------------------------------------------------------------------

    def champion_analysis(self, champion_genome: dict[str, Any] | None = None) -> dict[str, Any]:
        """Describe the champion genome's strategy in human-readable terms.

        Translates raw parameter values into a natural-language paragraph that
        explains the strategy's behaviour — entry conditions, risk profile,
        position sizing, and pair selection.

        Args:
            champion_genome: Optional dict of genome parameters.  When ``None``,
                the champion is read from the loaded evolution log.

        Returns:
            Dict containing the raw genome parameters and a ``description`` string.

        Raises:
            RuntimeError: If no log data has been loaded and ``champion_genome`` is None.
        """
        if champion_genome is None:
            self._require_log()
            champion_genome = self._log["champion"]["genome"]

        g = champion_genome
        fitness = self._log.get("champion", {}).get("fitness", "unknown")
        champion_gen = self._log.get("champion", {}).get("generation", "unknown")

        # Build a natural-language description block.
        lines: list[str] = []

        fitness_str = f"{fitness:.4f}" if isinstance(fitness, float) else str(fitness)
        lines.append(
            f"Champion strategy from generation {champion_gen} "
            f"(fitness: {fitness_str})."
        )
        lines.append("")

        # Entry conditions
        lines.append("Entry conditions:")
        lines.append(
            f"  - Enter long when RSI drops below {g.get('rsi_oversold', '?'):.1f} "
            f"(oversold threshold), indicating a potential reversal from a recent selloff."
        )
        lines.append(
            f"  - Require MACD bullish crossover using fast EMA {g.get('macd_fast', '?')} "
            f"and slow EMA {g.get('macd_slow', '?')} periods for momentum confirmation."
        )
        lines.append(
            f"  - Require ADX above {g.get('adx_threshold', '?'):.1f} to confirm "
            f"that a trend is present and avoid choppy, sideways markets."
        )

        lines.append("")

        # Exit conditions
        stop_pct = g.get("stop_loss_pct", 0.0)
        tp_pct = g.get("take_profit_pct", 0.0)
        trail_pct = g.get("trailing_stop_pct", 0.0)
        max_hold = g.get("max_hold_candles", 0)
        rsi_ob = g.get("rsi_overbought", 70.0)

        lines.append("Exit conditions:")
        lines.append(
            f"  - Stop-loss at {stop_pct * 100:.2f}% below entry price, "
            f"limiting downside on any single trade."
        )
        lines.append(
            f"  - Take-profit at {tp_pct * 100:.2f}% above entry price "
            f"(risk/reward ratio: {tp_pct / stop_pct:.1f}x)."
        )
        lines.append(
            f"  - Trailing stop at {trail_pct * 100:.2f}% from peak equity to "
            f"lock in profits during sustained trends."
        )
        lines.append(
            f"  - Force-exit after {max_hold} candles to prevent stale positions."
        )
        lines.append(
            f"  - Also exit when RSI rises above {rsi_ob:.1f} (overbought)."
        )

        lines.append("")

        # Position sizing and portfolio
        pos_size = g.get("position_size_pct", 0.0)
        max_pos = g.get("max_positions", 1)
        pairs: list[str] = g.get("pairs", [])

        lines.append("Position sizing and portfolio:")
        lines.append(
            f"  - Deploy {pos_size * 100:.1f}% of equity per position "
            f"(maximum simultaneous exposure: {pos_size * max_pos * 100:.1f}% across "
            f"{max_pos} position{'s' if max_pos != 1 else ''})."
        )
        lines.append(
            f"  - Tradeable pairs: {', '.join(pairs)}."
        )

        # Risk characterisation
        lines.append("")
        lines.append("Risk profile:")
        if stop_pct <= 0.02:
            lines.append("  - Tight stop-loss: conservative capital protection.")
        elif stop_pct <= 0.035:
            lines.append("  - Moderate stop-loss: balanced risk/reward.")
        else:
            lines.append("  - Wide stop-loss: tolerates larger drawdowns for bigger moves.")

        if pos_size <= 0.07:
            lines.append("  - Small position size: low per-trade risk.")
        elif pos_size <= 0.13:
            lines.append("  - Medium position size: moderate per-trade risk.")
        else:
            lines.append("  - Large position size: higher per-trade risk, higher potential reward.")

        description = "\n".join(lines)

        return {
            "genome": champion_genome,
            "description": description,
            "fitness": fitness,
            "generation": champion_gen,
        }

    # ------------------------------------------------------------------
    # Platform-connected analysis
    # ------------------------------------------------------------------

    async def run_baseline_comparison(
        self,
        rest_client: Any,
        champion_genome: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run champion vs random baseline in a battle and return comparison metrics.

        Creates two platform agents — one configured with the champion strategy,
        one with a default/random strategy — runs a short historical battle between
        them, and returns the per-agent performance metrics.

        Args:
            rest_client: Authenticated :class:`~agent.tools.rest_tools.PlatformRESTClient`.
            champion_genome: Champion genome dict.  Uses the log champion when ``None``.

        Returns:
            Dict with ``champion`` and ``baseline`` sub-dicts containing battle
            performance metrics, and a ``verdict`` string.
        """
        if champion_genome is None:
            self._require_log()
            champion_genome = self._log["champion"]["genome"]

        try:
            from agent.config import AgentConfig  # noqa: PLC0415
            from agent.strategies.evolutionary.genome import StrategyGenome  # noqa: PLC0415

            agent_cfg = AgentConfig()
            genome = StrategyGenome(**champion_genome)
            strategy_def = genome.to_strategy_definition()

            # Create champion strategy on the platform.
            champ_result = await rest_client.create_strategy(
                name="analyze-champion",
                description="Champion genome for baseline comparison",
                definition=strategy_def,
            )
            if "error" in champ_result:
                return {"error": f"Failed to create champion strategy: {champ_result['error']}"}
            champ_strategy_id = champ_result.get("strategy_id", "")

            # Create baseline (random genome) strategy.
            baseline_genome = StrategyGenome()  # defaults = a reasonable random strategy
            baseline_def = baseline_genome.to_strategy_definition()
            base_result = await rest_client.create_strategy(
                name="analyze-baseline",
                description="Random baseline for champion comparison",
                definition=baseline_def,
            )
            if "error" in base_result:
                return {"error": f"Failed to create baseline strategy: {base_result['error']}"}
            base_strategy_id = base_result.get("strategy_id", "")

            # Create two agents for the battle.
            champ_agent = await rest_client._post(
                "/api/v1/agents",
                {"name": "analyze-champion-agent", "starting_balance": "5000"},
            )
            base_agent = await rest_client._post(
                "/api/v1/agents",
                {"name": "analyze-baseline-agent", "starting_balance": "5000"},
            )
            champ_agent_id = champ_agent.get("agent_id", "")
            base_agent_id = base_agent.get("agent_id", "")

            # Run a historical battle between the two agents.
            config_snapshot: dict[str, Any] = self._log.get("config", {})
            hist_start = config_snapshot.get("historical_start", "2024-01-01T00:00:00Z")
            hist_end = config_snapshot.get("historical_end", "2024-01-08T00:00:00Z")

            battle_result = await rest_client._post(
                "/api/v1/battles",
                {
                    "mode": "historical",
                    "participant_agent_ids": [champ_agent_id, base_agent_id],
                    "historical_start": hist_start,
                    "historical_end": hist_end,
                    "preset": "historical_week",
                },
            )
            battle_id = battle_result.get("battle_id", "")

            if not battle_id:
                return {"error": "Battle creation returned no battle_id"}

            # Wait for battle completion (poll up to 10 min).
            final: dict[str, Any] = {}
            for _ in range(120):
                await asyncio.sleep(5)
                status_resp = await rest_client._get(f"/api/v1/battles/{battle_id}")
                state = status_resp.get("status", "")
                if state in {"completed", "cancelled", "failed"}:
                    final = status_resp
                    break

            if not final:
                return {"error": "Battle did not complete within the timeout window"}

            # Extract metrics for each agent from the rankings.
            rankings: list[dict[str, Any]] = final.get("rankings", [])
            champ_metrics: dict[str, Any] = {}
            base_metrics: dict[str, Any] = {}
            for r in rankings:
                if r.get("agent_id") == champ_agent_id:
                    champ_metrics = r
                elif r.get("agent_id") == base_agent_id:
                    base_metrics = r

            # Simple verdict.
            champ_roi = float(champ_metrics.get("total_return_pct", 0))
            base_roi = float(base_metrics.get("total_return_pct", 0))
            if champ_roi > base_roi:
                verdict = f"Champion outperformed baseline by {champ_roi - base_roi:.2f}% ROI."
            elif champ_roi < base_roi:
                verdict = f"Baseline outperformed champion by {base_roi - champ_roi:.2f}% ROI."
            else:
                verdict = "Champion and baseline performed identically."

            return {
                "battle_id": battle_id,
                "champion": champ_metrics,
                "baseline": base_metrics,
                "verdict": verdict,
            }

        except Exception as exc:  # noqa: BLE001
            logger.warning("analyze.baseline_comparison_failed", error=str(exc))
            return {"error": str(exc)}

    async def trade_behavior(
        self,
        battle_id: str,
        rest_client: Any,
    ) -> dict[str, Any]:
        """Analyse trade patterns from a completed battle replay.

        Calls ``GET /api/v1/battles/{id}/replay`` and analyses the trades
        to extract: average hold duration, most-traded pairs, entry/exit
        patterns, and win rate.

        Args:
            battle_id: Platform battle ID to replay.
            rest_client: Authenticated :class:`~agent.tools.rest_tools.PlatformRESTClient`.

        Returns:
            Dict with keys ``avg_hold_candles``, ``most_traded_pairs``,
            ``entry_exit_patterns``, ``win_rate``, ``total_trades``.
        """
        try:
            replay = await rest_client._get(f"/api/v1/battles/{battle_id}/replay")
        except Exception as exc:  # noqa: BLE001
            logger.warning("analyze.replay_fetch_failed", battle_id=battle_id, error=str(exc))
            return {"error": str(exc)}

        trades: list[dict[str, Any]] = replay.get("trades", [])
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": None,
                "avg_hold_candles": None,
                "most_traded_pairs": [],
                "entry_exit_patterns": {},
                "note": "No trades found in replay data.",
            }

        total_trades = len(trades)

        # Win rate — a trade is a win if realised_pnl > 0.
        wins = sum(1 for t in trades if float(t.get("realized_pnl", 0)) > 0)
        win_rate = round(wins / total_trades * 100, 2) if total_trades > 0 else 0.0

        # Average hold duration in candles.
        hold_durations: list[int] = []
        for t in trades:
            hold = t.get("hold_candles") or t.get("duration_candles")
            if hold is not None:
                hold_durations.append(int(hold))
        avg_hold = round(statistics.mean(hold_durations), 2) if hold_durations else None

        # Most-traded pairs.
        pair_counter: Counter[str] = Counter(
            t.get("symbol", "UNKNOWN") for t in trades
        )
        most_traded_pairs: list[dict[str, Any]] = [
            {"pair": pair, "count": count}
            for pair, count in pair_counter.most_common(10)
        ]

        # Entry / exit patterns: count by entry reason and exit reason.
        entry_patterns: Counter[str] = Counter(
            t.get("entry_reason", "unknown") for t in trades
        )
        exit_patterns: Counter[str] = Counter(
            t.get("exit_reason", "unknown") for t in trades
        )

        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "avg_hold_candles": avg_hold,
            "most_traded_pairs": most_traded_pairs,
            "entry_exit_patterns": {
                "entries": dict(entry_patterns.most_common()),
                "exits": dict(exit_patterns.most_common()),
            },
        }

    # ------------------------------------------------------------------
    # Full report generation
    # ------------------------------------------------------------------

    def generate_report(
        self,
        baseline_comparison: dict[str, Any] | None = None,
        trade_behavior_data: dict[str, Any] | None = None,
    ) -> EvolutionReport:
        """Assemble an :class:`EvolutionReport` from all available analyses.

        Runs the offline analyses (:meth:`fitness_curve`, :meth:`parameter_convergence`,
        :meth:`champion_analysis`) and embeds any pre-computed live results passed in.

        Args:
            baseline_comparison: Result from :meth:`run_baseline_comparison`,
                or ``None`` to omit.
            trade_behavior_data: Result from :meth:`trade_behavior`, or ``None``
                to omit.

        Returns:
            A fully populated :class:`EvolutionReport`.

        Raises:
            RuntimeError: If no log data has been loaded.
        """
        self._require_log()

        curve = self.fitness_curve()
        convergence = self.parameter_convergence()
        champion = self.champion_analysis()

        # Config snapshot — safe subset of the evolution log config.
        config_snapshot: dict[str, Any] = {
            k: str(v) if not isinstance(v, (int, float, str, bool, type(None))) else v
            for k, v in self._log.get("config", {}).items()
        }

        return EvolutionReport(
            timestamp=datetime.now(UTC).isoformat(),
            config_snapshot=config_snapshot,
            fitness_curve=curve,
            convergence={name: conv for name, conv in convergence.items()},
            champion=champion,
            baseline_comparison=baseline_comparison,
            trade_behavior=trade_behavior_data,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_log(self) -> None:
        """Raise RuntimeError if no log has been loaded.

        Raises:
            RuntimeError: When ``self._log`` is empty.
        """
        if not self._log:
            raise RuntimeError(
                "No evolution log loaded. Call load_log(path) first."
            )


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list.  Defaults to ``sys.argv[1:]``.

    Returns:
        Parsed :class:`argparse.Namespace`.
    """
    parser = argparse.ArgumentParser(
        prog="python -m agent.strategies.evolutionary.analyze",
        description=(
            "Analyse a completed evolution run and produce a JSON report. "
            "Offline analysis (fitness curve, convergence, champion description) "
            "works without a running platform. "
            "Pass --no-baseline to skip the live battle comparison."
        ),
    )
    parser.add_argument(
        "--log-path",
        dest="log_path",
        type=str,
        default=str(_DEFAULT_LOG_PATH),
        metavar="PATH",
        help=(
            "Path to evolution_log.json (default: results/evolution_log.json "
            "relative to this file)."
        ),
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        type=str,
        default=str(_REPORTS_DIR),
        metavar="DIR",
        help="Directory to write the report JSON file (default: agent/reports/).",
    )
    parser.add_argument(
        "--no-baseline",
        dest="skip_baseline",
        action="store_true",
        default=False,
        help="Skip the champion vs baseline live battle comparison.",
    )
    parser.add_argument(
        "--battle-id",
        dest="battle_id",
        type=str,
        default=None,
        metavar="ID",
        help=(
            "Existing battle ID to analyse trade behaviour from. "
            "When omitted, trade behaviour is derived from the baseline battle "
            "(if --no-baseline is not set)."
        ),
    )
    return parser.parse_args(argv)


def _configure_logging() -> None:
    """Configure structlog to mirror the rest of the agent package."""
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
    """Async entry point: load log, run analyses, write report.

    Args:
        argv: Optional argument list for testing; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code: 0 on success, 1 on fatal error.
    """
    _configure_logging()
    args = _parse_args(argv)

    analyzer = EvolutionAnalyzer()

    # Load and validate the evolution log.
    try:
        analyzer.load_log(args.log_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    print(f"[analyze] loaded log from {args.log_path}")

    # --- Offline analyses (always run) ---
    baseline_comparison: dict[str, Any] | None = None
    trade_behavior_data: dict[str, Any] | None = None
    battle_id_for_replay: str | None = args.battle_id

    # --- Online analyses (optional; require a running platform) ---
    if not args.skip_baseline:
        try:
            from agent.config import AgentConfig  # noqa: PLC0415
            from agent.tools.rest_tools import PlatformRESTClient  # noqa: PLC0415

            agent_cfg = AgentConfig()
            print("[analyze] running champion vs baseline battle comparison...")
            async with PlatformRESTClient(agent_cfg) as rest_client:
                champion_genome = analyzer._log["champion"]["genome"]
                baseline_comparison = await analyzer.run_baseline_comparison(
                    rest_client=rest_client,
                    champion_genome=champion_genome,
                )

                # If baseline battle succeeded, use that battle for trade behaviour.
                if "error" not in baseline_comparison and battle_id_for_replay is None:
                    battle_id_for_replay = baseline_comparison.get("battle_id")

                if battle_id_for_replay:
                    print(
                        f"[analyze] analysing trade behaviour for battle {battle_id_for_replay}..."
                    )
                    trade_behavior_data = await analyzer.trade_behavior(
                        battle_id=battle_id_for_replay,
                        rest_client=rest_client,
                    )

        except Exception as exc:  # noqa: BLE001
            logger.warning("analyze.online_analysis_failed", error=str(exc))
            print(
                f"[analyze] WARNING: online analysis failed ({exc}). "
                "Producing offline-only report.",
                file=sys.stderr,
            )
    elif args.battle_id:
        # --battle-id given with --no-baseline: fetch replay only.
        try:
            from agent.config import AgentConfig  # noqa: PLC0415
            from agent.tools.rest_tools import PlatformRESTClient  # noqa: PLC0415

            agent_cfg = AgentConfig()
            print(f"[analyze] analysing trade behaviour for battle {args.battle_id}...")
            async with PlatformRESTClient(agent_cfg) as rest_client:
                trade_behavior_data = await analyzer.trade_behavior(
                    battle_id=args.battle_id,
                    rest_client=rest_client,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("analyze.trade_behavior_failed", error=str(exc))
            print(f"[analyze] WARNING: trade behaviour analysis failed: {exc}", file=sys.stderr)

    # Build report.
    print("[analyze] generating report...")
    report = analyzer.generate_report(
        baseline_comparison=baseline_comparison,
        trade_behavior_data=trade_behavior_data,
    )

    # Write report to disk.
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"evolution-report-{ts}.json"

    report_path.write_text(
        json.dumps(report.model_dump(), indent=2, default=str),
        encoding="utf-8",
    )

    print(f"[analyze] report written to {report_path}")

    # Print a brief summary to stdout.
    curve = report.fitness_curve
    if curve:
        first = curve[0]
        last = curve[-1]
        print(
            f"\n[analyze] fitness trajectory:\n"
            f"  gen 1  — best: {first.best_fitness:.4f}, avg: {first.avg_fitness:.4f}\n"
            f"  gen {last.generation}  — best: {last.best_fitness:.4f}, avg: {last.avg_fitness:.4f}"
        )

    converged_params = [
        name for name, c in report.convergence.items() if c.converged
    ]
    variable_params = [
        name for name, c in report.convergence.items() if not c.converged
    ]
    print(
        f"\n[analyze] parameter convergence:\n"
        f"  converged ({len(converged_params)}): {', '.join(converged_params) or 'none'}\n"
        f"  variable  ({len(variable_params)}): {', '.join(variable_params) or 'none'}"
    )

    champ_gen = report.champion.get("generation", "?")
    champ_fit = report.champion.get("fitness", "?")
    print(f"\n[analyze] champion: generation {champ_gen}, fitness {champ_fit}")

    if report.baseline_comparison and "error" not in report.baseline_comparison:
        print(f"[analyze] baseline: {report.baseline_comparison.get('verdict', '')}")

    logger.info(
        "analyze.complete",
        report_path=str(report_path),
        generations=len(curve),
        converged_params=len(converged_params),
    )

    return 0


def main(argv: list[str] | None = None) -> None:
    """Synchronous entry point used by ``python -m agent.strategies.evolutionary.analyze``.

    Args:
        argv: Optional argument list; defaults to ``sys.argv[1:]``.
    """
    exit_code = asyncio.run(_main(argv))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
