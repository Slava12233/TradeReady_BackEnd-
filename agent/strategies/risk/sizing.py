"""Dynamic position sizer for the risk strategies layer.

Computes a volatility- and drawdown-adjusted position size from a base
allocation fraction.  The adjustment logic applies two independent scaling
factors and then clamps the result to the configured bounds:

1. **Volatility adjustment** — scales the size *inversely* with the ratio of
   current ATR to the rolling average ATR.  When the market is more volatile
   than usual (``atr > avg_atr``), the size is reduced; when calmer, it grows.
   Formula: ``size *= avg_atr / atr``

2. **Drawdown adjustment** — linearly reduces the size as drawdown grows.
   Formula: ``size *= (1 - drawdown_pct * 2)``
   At 0 % drawdown the multiplier is 1.0 (no change).
   At 25 % drawdown the multiplier is 0.5 (half size).
   At 50 %+ drawdown the multiplier floors at 0.0 before the clamp rescues it.

3. **Clamp** — the result is always kept in the range
   ``[0.01, config.max_single_position]`` so the output is never zero,
   negative, or above the single-position limit.

All financial fractions are handled as :class:`decimal.Decimal` for
precision.  ATR values may be passed as ``float`` or ``Decimal``; they are
converted internally.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard floor for any sized position — prevents infinitesimally small orders.
# 1 % of equity is the absolute minimum that makes sense for the platform.
_ABSOLUTE_MIN_SIZE = Decimal("0.01")

# Quantisation for output sizes (4 d.p. → 0.01 % resolution).
_D4 = Decimal("0.0001")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class SizerConfig(BaseSettings):
    """Configurable bounds for the dynamic position sizer.

    Attributes:
        max_single_position: Upper bound for any single position size as a
            fraction of equity (default 0.10 = 10 %).  Matches the default
            in :class:`~agent.strategies.risk.RiskConfig` so the two layers
            stay consistent.
        min_single_position: Lower bound — the smallest meaningful trade size
            as a fraction of equity (default 0.01 = 1 %).  Prevents near-zero
            orders that would incur fees disproportionate to the position.

    Example::

        cfg = SizerConfig(max_single_position=Decimal("0.15"))
        sizer = DynamicSizer(config=cfg)
    """

    model_config = SettingsConfigDict(
        env_prefix="SIZER_",
        case_sensitive=False,
        extra="ignore",
    )

    max_single_position: Decimal = Field(
        default=Decimal("0.10"),
        description="Maximum position size as a fraction of equity (0–1).",
    )
    min_single_position: Decimal = Field(
        default=_ABSOLUTE_MIN_SIZE,
        description="Minimum meaningful position size as a fraction of equity (0–1).",
    )


# ---------------------------------------------------------------------------
# Dynamic sizer
# ---------------------------------------------------------------------------


class DynamicSizer:
    """Computes a volatility- and drawdown-adjusted position size.

    The sizer does *not* access the platform or any external data source.
    All inputs are passed directly to :meth:`calculate_size`; the caller is
    responsible for supplying current ATR, rolling-average ATR, and drawdown
    from the appropriate data pipeline.

    Args:
        config: Sizer configuration with position-size bounds.  Defaults to
            :class:`SizerConfig` with standard thresholds.

    Example::

        sizer = DynamicSizer()
        adjusted = sizer.calculate_size(
            base_size_pct=0.08,
            atr=120.5,
            avg_atr=95.0,
            drawdown_pct=0.04,
        )
        # adjusted will be < 0.08 because atr > avg_atr and drawdown > 0
    """

    def __init__(self, config: SizerConfig | None = None) -> None:
        self._config = config or SizerConfig()
        self._log = logger.bind(component="DynamicSizer")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def calculate_size(
        self,
        base_size_pct: float | Decimal,
        atr: float | Decimal,
        avg_atr: float | Decimal,
        drawdown_pct: float | Decimal,
    ) -> float:
        """Compute the adjusted position size fraction.

        Applies volatility and drawdown scaling to ``base_size_pct`` and
        clamps the result to ``[min_single_position, max_single_position]``.

        Args:
            base_size_pct: Starting allocation as a fraction of equity,
                e.g. ``0.08`` for 8 %.  Must be positive; negative or zero
                values are clamped to ``min_single_position``.
            atr: Current Average True Range for the trading pair.  Must be
                positive; a zero or negative value is treated as equal to
                ``avg_atr`` (no volatility adjustment applied).
            avg_atr: Rolling average ATR (the baseline).  Must be positive;
                a zero or negative value is treated as equal to ``atr``
                (no volatility adjustment applied).
            drawdown_pct: Current peak-to-trough drawdown as a fraction,
                e.g. ``0.05`` for 5 %.  Negative values are treated as 0
                (no drawdown).

        Returns:
            Adjusted position size as a ``float`` in
            ``[min_single_position, max_single_position]``.  Never zero,
            negative, or above the configured maximum.

        Example::

            # High volatility: atr (200) > avg_atr (100) → half the base size
            adjusted = sizer.calculate_size(0.10, atr=200, avg_atr=100, drawdown_pct=0.0)
            # → 0.05 (before clamp; within bounds)

            # Low volatility: atr (50) < avg_atr (100) → double the base size
            adjusted = sizer.calculate_size(0.05, atr=50, avg_atr=100, drawdown_pct=0.0)
            # → 0.10 (clamped to max_single_position)
        """
        size = Decimal(str(base_size_pct))
        d_atr = Decimal(str(atr))
        d_avg_atr = Decimal(str(avg_atr))
        d_drawdown = Decimal(str(drawdown_pct))

        # Guard against non-positive drawdown (treat as zero).
        if d_drawdown < Decimal("0"):
            d_drawdown = Decimal("0")

        # ------------------------------------------------------------------
        # Step 1: Volatility adjustment
        # Apply only when both ATR values are positive to avoid division by
        # zero or nonsensical scaling.  When they are equal (or either is
        # zero) the multiplier is 1.0 (neutral).
        # ------------------------------------------------------------------
        if d_atr > Decimal("0") and d_avg_atr > Decimal("0"):
            vol_multiplier = d_avg_atr / d_atr
            size_before_vol = size
            size = size * vol_multiplier
            self._log.debug(
                "sizer_volatility_adjustment",
                atr=str(d_atr),
                avg_atr=str(d_avg_atr),
                multiplier=f"{float(vol_multiplier):.4f}",
                size_before=str(size_before_vol),
                size_after=str(size),
            )
        else:
            self._log.debug(
                "sizer_volatility_skipped",
                atr=str(d_atr),
                avg_atr=str(d_avg_atr),
                reason="non-positive ATR value(s)",
            )

        # ------------------------------------------------------------------
        # Step 2: Drawdown adjustment
        # Formula: size *= (1 - drawdown_pct * 2)
        # A drawdown of 0.50 (50%) makes the multiplier exactly 0.0 before
        # the clamp rescues it to min_single_position.
        # ------------------------------------------------------------------
        drawdown_multiplier = Decimal("1") - d_drawdown * Decimal("2")
        size_before_dd = size
        size = size * drawdown_multiplier
        self._log.debug(
            "sizer_drawdown_adjustment",
            drawdown_pct=f"{float(d_drawdown):.4f}",
            multiplier=f"{float(drawdown_multiplier):.4f}",
            size_before=str(size_before_dd),
            size_after=str(size),
        )

        # ------------------------------------------------------------------
        # Step 3: Clamp to configured bounds.
        # ------------------------------------------------------------------
        min_size = max(self._config.min_single_position, _ABSOLUTE_MIN_SIZE)
        max_size = self._config.max_single_position

        clamped = size.quantize(_D4, ROUND_HALF_UP)
        clamped = max(clamped, min_size)
        clamped = min(clamped, max_size)

        self._log.info(
            "sizer_result",
            base_size_pct=str(Decimal(str(base_size_pct))),
            adjusted_size_pct=str(clamped),
            atr=str(d_atr),
            avg_atr=str(d_avg_atr),
            drawdown_pct=f"{float(d_drawdown):.4f}",
        )

        return float(clamped)
