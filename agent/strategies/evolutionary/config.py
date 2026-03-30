"""EvolutionConfig — environment-driven configuration for the genetic algorithm loop.

All settings are read from environment variables with the ``EVO_`` prefix, or
can be overridden via the ``agent/.env`` file (which pydantic-settings reads
automatically if present).

Example usage::

    from agent.strategies.evolutionary.config import EvolutionConfig

    cfg = EvolutionConfig()
    print(cfg.population_size)   # 12
    print(cfg.generations)       # 30
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the .env file path relative to this file (agent/.env)
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"

# Supported fitness function identifiers.
_VALID_FITNESS_FNS: frozenset[str] = frozenset(
    [
        "sharpe_minus_drawdown",   # sharpe_ratio - 0.5 * max_drawdown_pct (legacy)
        "sharpe_only",             # sharpe_ratio alone
        "roi_only",                # return-on-investment percentage
        "composite",               # 5-factor OOS-weighted composite (default)
    ]
)


class EvolutionConfig(BaseSettings):
    """All runtime knobs for the evolutionary strategy optimisation loop.

    Every field maps 1-to-1 with an ``EVO_``-prefixed environment variable so
    a CI/CD pipeline or sweep script can override any value without code changes.

    Defaults are tuned for a 12-individual population run over 30 generations,
    which typically completes in under an hour against a week-long historical
    battle window.

    Example::

        # Default run
        cfg = EvolutionConfig()

        # Override via env:  EVO_GENERATIONS=10 EVO_POP_SIZE=6 python -m ...
        cfg = EvolutionConfig()
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        env_prefix="EVO_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Population ────────────────────────────────────────────────────────────

    population_size: int = Field(
        default=12,
        ge=2,
        description=(
            "Number of strategy genomes in each generation.  Must be >= 2. "
            "Larger populations explore more of the parameter space but require "
            "more battle slots per generation."
        ),
    )

    # ── Evolution loop ────────────────────────────────────────────────────────

    generations: int = Field(
        default=30,
        ge=1,
        description=(
            "Maximum number of generations to run before stopping.  "
            "Early stopping via convergence_threshold may terminate the loop "
            "before this limit is reached."
        ),
    )

    elite_pct: float = Field(
        default=0.2,
        gt=0.0,
        lt=1.0,
        description=(
            "Fraction of the population carried unchanged into the next "
            "generation (elitism).  Default 0.2 preserves the top 20 % "
            "and fills the rest via tournament selection + crossover + mutation."
        ),
    )

    mutation_rate: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description=(
            "Per-gene mutation probability for the ``mutate()`` operator.  "
            "Default 0.1 means ~10 % of the 17 genes are perturbed per genome, "
            "roughly 1–2 mutations per individual."
        ),
    )

    mutation_strength: float = Field(
        default=0.1,
        gt=0.0,
        description=(
            "Gaussian std expressed as a fraction of the parameter range.  "
            "0.1 = 10 % of each parameter's (hi - lo) span.  Larger values "
            "increase exploration; smaller values increase exploitation."
        ),
    )

    # ── Battle configuration ──────────────────────────────────────────────────

    battle_preset: str = Field(
        default="historical_week",
        description=(
            "Platform battle preset used for fitness evaluation.  "
            "One of: ``historical_day``, ``historical_week``, ``historical_month``.  "
            "Longer windows produce more reliable fitness estimates but take longer."
        ),
    )

    historical_start: date = Field(
        default=date(2024, 1, 1),
        description=(
            "Start date of the historical replay window used for battles.  "
            "Must be a date for which candle data exists in the platform database.  "
            "Format: YYYY-MM-DD."
        ),
    )

    historical_end: date = Field(
        default=date(2024, 1, 8),
        description=(
            "End date of the historical replay window (exclusive).  "
            "For ``historical_week``, a 7-day window from start is appropriate.  "
            "Format: YYYY-MM-DD."
        ),
    )

    # ── Convergence ───────────────────────────────────────────────────────────

    convergence_threshold: int = Field(
        default=5,
        ge=1,
        description=(
            "Number of consecutive generations with no improvement in the best "
            "fitness score before early stopping is triggered.  "
            "Default 5 prevents wasted compute when the population has plateaued."
        ),
    )

    # ── Fitness function ──────────────────────────────────────────────────────

    fitness_fn: str = Field(
        default="composite",
        description=(
            "Fitness function identifier used to score each genome.  "
            "Must be one of: ``composite`` (5-factor OOS-weighted, recommended), "
            "``sharpe_minus_drawdown`` (Sharpe - 0.5 × drawdown, legacy), "
            "``sharpe_only``, ``roi_only``."
        ),
    )

    # ── Out-of-sample split ───────────────────────────────────────────────────

    oos_split_ratio: float = Field(
        default=0.30,
        gt=0.0,
        lt=1.0,
        description=(
            "Fraction of the historical window reserved for out-of-sample (OOS) "
            "evaluation.  Default 0.30 means the last 30 % of the battle period "
            "is held out and never seen during in-sample fitness scoring.  "
            "OOS Sharpe feeds the composite fitness function to penalise "
            "strategies that overfit the in-sample window."
        ),
    )

    # ── Reproducibility ───────────────────────────────────────────────────────

    seed: int = Field(
        default=42,
        description=(
            "Master random seed passed to Population and all evolutionary "
            "operators.  Setting a fixed seed guarantees fully reproducible "
            "evolution runs.  Override with ``EVO_SEED=<n>`` or ``--seed``."
        ),
    )

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("fitness_fn")
    @classmethod
    def _validate_fitness_fn(cls, value: str) -> str:
        """Reject unknown fitness function identifiers early.

        Args:
            value: The ``fitness_fn`` field value before assignment.

        Returns:
            The validated value, unchanged.

        Raises:
            ValueError: If ``value`` is not in ``_VALID_FITNESS_FNS``.
        """
        if value not in _VALID_FITNESS_FNS:
            raise ValueError(
                f"Unknown fitness_fn '{value}'. "
                f"Valid options: {sorted(_VALID_FITNESS_FNS)}"
            )
        return value

    @field_validator("oos_split_ratio")
    @classmethod
    def _validate_oos_split_ratio(cls, value: float) -> float:
        """Ensure OOS split leaves enough data for both in-sample and OOS periods.

        Args:
            value: The ``oos_split_ratio`` field value before assignment.

        Returns:
            The validated value, unchanged.

        Raises:
            ValueError: If ``value`` is outside the reasonable range (0.10, 0.50].
        """
        if not 0.10 <= value <= 0.50:
            raise ValueError(
                f"oos_split_ratio must be in [0.10, 0.50], got {value}. "
                "Values below 0.10 leave too little data for OOS evaluation; "
                "values above 0.50 make the in-sample window too short."
            )
        return value

    @field_validator("historical_end")
    @classmethod
    def _validate_date_range(cls, end: date, info: object) -> date:
        """Ensure historical_end is strictly after historical_start.

        Args:
            end: The ``historical_end`` field value.
            info: Pydantic validation info containing already-validated fields.

        Returns:
            The validated ``end`` date, unchanged.

        Raises:
            ValueError: If ``end`` is not after ``historical_start``.
        """
        # ``info.data`` is only populated when ``historical_start`` validated first.
        start: date | None = getattr(info, "data", {}).get("historical_start")
        if start is not None and end <= start:
            raise ValueError(
                f"historical_end ({end}) must be after historical_start ({start})"
            )
        return end

    # ── Derived helpers ───────────────────────────────────────────────────────

    @property
    def historical_window(self) -> tuple[str, str]:
        """Return the full historical battle window as ISO-8601 UTC strings.

        Returns:
            A ``(start_iso, end_iso)`` tuple ready for
            :meth:`~agent.strategies.evolutionary.battle_runner.BattleRunner.run_battle`.
        """
        return (
            f"{self.historical_start.isoformat()}T00:00:00Z",
            f"{self.historical_end.isoformat()}T00:00:00Z",
        )

    @property
    def is_split(self) -> tuple[str, str, str]:
        """Return the in-sample / OOS split points as ISO-8601 UTC strings.

        Splits the total window at the ``oos_split_ratio`` boundary so the
        in-sample battle runs on ``[historical_start, split_date)`` and the
        OOS battle runs on ``[split_date, historical_end)``.

        Example with default 0.30 ratio over 2024-01-01 → 2024-01-08 (7 days):
            - in-sample:  2024-01-01 → 2024-01-06  (4.9 days ≈ 70 %)
            - OOS:        2024-01-06 → 2024-01-08  (2.1 days ≈ 30 %)

        Returns:
            A ``(is_start_iso, split_iso, oos_end_iso)`` triple.
        """
        total_days = (self.historical_end - self.historical_start).days
        oos_days = max(1, round(total_days * self.oos_split_ratio))
        is_days = total_days - oos_days
        split_date = self.historical_start + timedelta(days=is_days)
        return (
            f"{self.historical_start.isoformat()}T00:00:00Z",
            f"{split_date.isoformat()}T00:00:00Z",
            f"{self.historical_end.isoformat()}T00:00:00Z",
        )

    @property
    def in_sample_window(self) -> tuple[str, str]:
        """Return the in-sample window (first 70 % by default).

        Returns:
            ``(start_iso, split_iso)`` for the in-sample battle.
        """
        is_start, split, _ = self.is_split
        return (is_start, split)

    @property
    def oos_window(self) -> tuple[str, str]:
        """Return the out-of-sample window (last 30 % by default).

        Returns:
            ``(split_iso, end_iso)`` for the OOS evaluation battle.
        """
        _, split, oos_end = self.is_split
        return (split, oos_end)
