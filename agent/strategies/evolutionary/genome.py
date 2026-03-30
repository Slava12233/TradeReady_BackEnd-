"""StrategyGenome — maps strategy parameters to a fixed-length float vector.

Each genome represents one candidate trading strategy.  Parameters are kept
as plain Python types (int / float / list) for compatibility with numpy and
Stable-Baselines3.  Money-adjacent ratios (stop_loss_pct, etc.) are floats
because they are pure dimensionless ratios, not monetary amounts — Decimal is
only needed when the value represents actual USDT.

The genome converts to/from a numpy float64 vector so evolutionary operators
can work uniformly on the parameter space.  The `to_strategy_definition()`
method produces the JSONB-compatible dict that the platform's StrategyDefinition
model accepts.
"""

from __future__ import annotations

import random
from decimal import Decimal
from typing import Any

import numpy as np
from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Parameter bounds — every ``(lo, hi)`` pair defines the valid search range.
# Values outside this range are invalid; ``clip_genome`` enforces the bounds
# after mutation / crossover.
# ---------------------------------------------------------------------------

# Pairs that the platform actually supports for backtesting.  Genomes pick a
# random non-empty subset of these during initialisation.
AVAILABLE_PAIRS: list[str] = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "ADAUSDT",
    "XRPUSDT",
]

# Continuous scalar bounds: (lo, hi).
SCALAR_BOUNDS: dict[str, tuple[float, float]] = {
    "rsi_oversold":       (20.0, 40.0),
    "rsi_overbought":     (60.0, 80.0),
    "adx_threshold":      (15.0, 35.0),
    "stop_loss_pct":      (0.01, 0.05),   # ratio, not Decimal — no money value
    "take_profit_pct":    (0.02, 0.10),   # ratio
    "trailing_stop_pct":  (0.005, 0.03),  # ratio
    "position_size_pct":  (0.03, 0.20),   # ratio (3 %–20 %)
}

# Integer parameter bounds: (lo, hi) — both inclusive.
INT_BOUNDS: dict[str, tuple[int, int]] = {
    "macd_fast":       (8, 15),
    "macd_slow":       (20, 30),
    "max_hold_candles": (10, 200),
    "max_positions":   (1, 5),
}

# Canonical parameter order for the vector representation.  Pairs are encoded
# as a binary presence mask appended after the scalar / int params.
_SCALAR_KEYS: list[str] = list(SCALAR_BOUNDS.keys())          # 7 elements
_INT_KEYS: list[str] = list(INT_BOUNDS.keys())                 # 4 elements
_SCALAR_LEN = len(_SCALAR_KEYS)                                # 7
_INT_LEN = len(_INT_KEYS)                                      # 4
_PAIRS_LEN = len(AVAILABLE_PAIRS)                              # 6
VECTOR_LEN = _SCALAR_LEN + _INT_LEN + _PAIRS_LEN              # 17


class StrategyGenome(BaseModel):
    """One candidate strategy in the evolutionary population.

    All float/int fields have explicit bounds documented in ``SCALAR_BOUNDS``
    and ``INT_BOUNDS``.  The ``pairs`` list must be a non-empty subset of
    ``AVAILABLE_PAIRS``.
    """

    # --- RSI thresholds -------------------------------------------------------
    rsi_oversold: float = Field(
        default=30.0,
        ge=20.0, le=40.0,
        description="Enter long when RSI drops below this value (20–40)",
    )
    rsi_overbought: float = Field(
        default=70.0,
        ge=60.0, le=80.0,
        description="Exit or enter short when RSI rises above this value (60–80)",
    )

    # --- MACD periods --------------------------------------------------------
    macd_fast: int = Field(
        default=12,
        ge=8, le=15,
        description="Fast EMA period for MACD calculation (8–15)",
    )
    macd_slow: int = Field(
        default=26,
        ge=20, le=30,
        description="Slow EMA period for MACD calculation (20–30)",
    )

    # --- Trend filter --------------------------------------------------------
    adx_threshold: float = Field(
        default=25.0,
        ge=15.0, le=35.0,
        description="Minimum ADX for trend-following entry (15–35)",
    )

    # --- Risk parameters (pure ratios, not Decimal) -------------------------
    stop_loss_pct: float = Field(
        default=0.02,
        ge=0.01, le=0.05,
        description="Stop-loss distance from entry price as a decimal ratio (0.01–0.05)",
    )
    take_profit_pct: float = Field(
        default=0.04,
        ge=0.02, le=0.10,
        description="Take-profit distance from entry price as a decimal ratio (0.02–0.10)",
    )
    trailing_stop_pct: float = Field(
        default=0.015,
        ge=0.005, le=0.03,
        description="Trailing stop distance from peak equity as a decimal ratio (0.005–0.03)",
    )

    # --- Position sizing (ratio, not Decimal) --------------------------------
    position_size_pct: float = Field(
        default=0.10,
        ge=0.03, le=0.20,
        description=(
            "Fraction of equity to deploy per position (0.03–0.20). "
            "Stored as float ratio; converted to Decimal % when building StrategyDefinition."
        ),
    )

    # --- Hold duration -------------------------------------------------------
    max_hold_candles: int = Field(
        default=50,
        ge=10, le=200,
        description="Maximum candles to hold an open position before forced exit (10–200)",
    )

    # --- Portfolio limits ----------------------------------------------------
    max_positions: int = Field(
        default=3,
        ge=1, le=5,
        description="Maximum simultaneous open positions (1–5)",
    )

    # --- Trading pairs -------------------------------------------------------
    pairs: list[str] = Field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT"],
        min_length=1,
        description="Trading pairs to include; must be a non-empty subset of AVAILABLE_PAIRS",
    )

    @model_validator(mode="after")
    def _validate_pairs(self) -> "StrategyGenome":
        """Ensure pairs are valid, unique, and non-empty."""
        cleaned = [p.upper().strip() for p in self.pairs if p.strip() in AVAILABLE_PAIRS]
        if not cleaned:
            # Fall back to the first available pair rather than raising, so
            # random init never fails.
            cleaned = [AVAILABLE_PAIRS[0]]
        self.pairs = list(dict.fromkeys(cleaned))  # deduplicate, preserve order
        return self

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_random(cls, seed: int | None = None) -> "StrategyGenome":
        """Create a genome with uniformly sampled parameters within bounds.

        Args:
            seed: Optional random seed for reproducibility.

        Returns:
            A new StrategyGenome with all parameters within their valid ranges.
        """
        rng = random.Random(seed)
        np_rng = np.random.default_rng(seed)

        # Sample scalar parameters.
        scalar_vals: dict[str, float] = {
            key: float(np_rng.uniform(lo, hi))
            for key, (lo, hi) in SCALAR_BOUNDS.items()
        }

        # Sample integer parameters.
        int_vals: dict[str, int] = {
            key: int(rng.randint(lo, hi))
            for key, (lo, hi) in INT_BOUNDS.items()
        }

        # Sample a random non-empty subset of pairs (1 to all).
        n_pairs = rng.randint(1, len(AVAILABLE_PAIRS))
        sampled_pairs = rng.sample(AVAILABLE_PAIRS, k=n_pairs)

        return cls(**scalar_vals, **int_vals, pairs=sampled_pairs)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Vector conversion — for evolutionary operators
    # ------------------------------------------------------------------

    def to_vector(self) -> np.ndarray:
        """Serialise the genome to a float64 numpy vector of length ``VECTOR_LEN``.

        Layout:
            [0:7]   — scalar parameters in ``_SCALAR_KEYS`` order
            [7:11]  — integer parameters in ``_INT_KEYS`` order
            [11:17] — binary pair mask (1.0 if pair is active, 0.0 otherwise)

        Returns:
            1-D float64 array of length ``VECTOR_LEN`` (17).
        """
        scalar_vals = [getattr(self, k) for k in _SCALAR_KEYS]
        int_vals = [float(getattr(self, k)) for k in _INT_KEYS]
        pair_mask = [1.0 if p in self.pairs else 0.0 for p in AVAILABLE_PAIRS]
        return np.array(scalar_vals + int_vals + pair_mask, dtype=np.float64)

    @classmethod
    def from_vector(cls, vec: np.ndarray) -> "StrategyGenome":
        """Reconstruct a genome from a float64 numpy vector.

        The vector must have been produced by ``to_vector()`` or by evolutionary
        operators operating on the same layout.  Out-of-bound values are clipped
        to the valid range before constructing the model (clip happens inside
        ``clip_genome``, which callers are expected to apply before calling this).

        Args:
            vec: 1-D array of length ``VECTOR_LEN`` (17).

        Returns:
            A validated StrategyGenome.

        Raises:
            ValueError: If ``vec`` does not have the expected length.
        """
        if len(vec) != VECTOR_LEN:
            raise ValueError(f"Expected vector length {VECTOR_LEN}, got {len(vec)}")

        kwargs: dict[str, Any] = {}

        # Scalars
        for i, key in enumerate(_SCALAR_KEYS):
            lo, hi = SCALAR_BOUNDS[key]
            kwargs[key] = float(np.clip(vec[i], lo, hi))

        # Integers
        offset = _SCALAR_LEN
        for j, key in enumerate(_INT_KEYS):
            lo, hi = INT_BOUNDS[key]
            kwargs[key] = int(np.clip(round(vec[offset + j]), lo, hi))

        # Pairs — any mask value >= 0.5 is treated as active
        pair_offset = _SCALAR_LEN + _INT_LEN
        active_pairs = [
            AVAILABLE_PAIRS[k]
            for k in range(_PAIRS_LEN)
            if vec[pair_offset + k] >= 0.5
        ]
        kwargs["pairs"] = active_pairs if active_pairs else [AVAILABLE_PAIRS[0]]

        return cls(**kwargs)

    # ------------------------------------------------------------------
    # Platform integration
    # ------------------------------------------------------------------

    def to_strategy_definition(self) -> dict[str, Any]:
        """Convert this genome to a platform StrategyDefinition-compatible dict.

        The returned dict matches the JSONB schema expected by
        ``src/strategies/models.py::StrategyDefinition``.  It can be passed
        directly as the ``definition`` field when creating a strategy version
        via the REST API or MCP tools.

        Returns:
            A dict serialisable to JSON that passes StrategyDefinition validation.
        """
        # position_size_pct is stored as a float ratio (e.g., 0.10 = 10 %).
        # The platform schema expects Decimal representing the percentage value
        # (e.g., Decimal("10")).  Convert here to avoid float precision issues.
        position_size_decimal = str(Decimal(str(round(self.position_size_pct * 100, 4))))

        # Convert ratio params to percentage strings where the schema expects %.
        # stop_loss_pct etc. in ExitConditions are in raw decimal form (0.02 = 2 %).
        # The executor applies them as: entry_price * (1 - stop_loss_pct / 100)
        # so we must convert our ratio to a percentage value for the schema.
        stop_loss_schema = round(self.stop_loss_pct * 100, 4)
        take_profit_schema = round(self.take_profit_pct * 100, 4)
        trailing_stop_schema = round(self.trailing_stop_pct * 100, 4)

        return {
            "pairs": self.pairs,
            "timeframe": "1h",
            "entry_conditions": {
                "rsi_below": round(self.rsi_oversold, 2),
                "macd_cross_above": True,
                "adx_above": round(self.adx_threshold, 2),
            },
            "exit_conditions": {
                "rsi_above": round(self.rsi_overbought, 2),
                "stop_loss_pct": stop_loss_schema,
                "take_profit_pct": take_profit_schema,
                "trailing_stop_pct": trailing_stop_schema,
                "max_hold_candles": self.max_hold_candles,
            },
            "position_size_pct": position_size_decimal,
            "max_positions": self.max_positions,
            "filters": {
                # Store MACD periods in the filters bag so the executor can pick
                # them up without extending the EntryConditions schema.
                "macd_fast": self.macd_fast,
                "macd_slow": self.macd_slow,
            },
            "model_type": "rule_based",
        }
