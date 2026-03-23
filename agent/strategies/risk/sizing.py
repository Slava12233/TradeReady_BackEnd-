"""Position sizing strategies for the risk strategies layer.

Three complementary sizing methods:

1. **DynamicSizer** — the original volatility- and drawdown-adjusted sizer.
   Scales a base allocation fraction by ``avg_atr / atr`` (volatility
   inverse) and by ``1 - drawdown_pct * 2`` (drawdown reduction), then
   clamps to configured bounds.

2. **KellyFractionalSizer** — implements the fractional Kelly criterion.
   The theoretical full-Kelly fraction is reduced by a configurable
   divisor (default: 2 for Half-Kelly, 4 for Quarter-Kelly) and clamped
   to the range ``[min_size_pct, max_size_pct]``::

       kelly_fraction = (win_rate * avg_win_loss_ratio - (1 - win_rate))
                        / avg_win_loss_ratio
       position_pct   = kelly_fraction / kelly_divisor

   Edge cases:
   - ``win_rate == 0.0``: full loss, Kelly = −1.0, returns 0.0.
   - ``avg_win_loss_ratio == 0.0``: undefined, returns 0.0.
   - Negative Kelly (losing strategy): returns 0.0 (no trade).

3. **HybridSizer** — combines Half-Kelly sizing with an ATR-based
   volatility adjustment.  The Kelly fraction is multiplied by the ratio
   ``target_vol / current_vol`` where current volatility is measured as
   ``atr / close_price`` and target volatility is the long-run baseline::

       kelly_pct     = KellyFractionalSizer.calculate_kelly_fraction(...)
       current_vol   = atr / close_price
       position_pct  = kelly_pct * (target_vol / current_vol)

   Zero ATR or zero close price are handled safely (Kelly fraction is
   returned unchanged when volatility adjustment cannot be computed).

All financial fractions are handled as :class:`decimal.Decimal` for
precision.  ATR and price values may be passed as ``float`` or
``Decimal``; they are converted internally.

Usage::

    from agent.strategies.risk.sizing import (
        SizingMethod,
        SizerConfig,
        DynamicSizer,
        KellyFractionalSizer,
        KellyConfig,
        HybridSizer,
        HybridConfig,
    )

    # Half-Kelly
    kelly_cfg = KellyConfig(kelly_divisor=2)
    kelly_sizer = KellyFractionalSizer(config=kelly_cfg)
    size = kelly_sizer.calculate_size(win_rate=0.55, avg_win_loss_ratio=1.5)

    # Hybrid (Kelly + ATR vol adjustment)
    hybrid_sizer = HybridSizer()
    size = hybrid_sizer.calculate_size(
        win_rate=0.55,
        avg_win_loss_ratio=1.5,
        atr=1200.0,
        close_price=42000.0,
    )

    # Method selection
    method = SizingMethod.KELLY
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

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

# Hard ceiling for any single position — never exceed 10 % by default.
_ABSOLUTE_MAX_SIZE = Decimal("0.10")

# Quantisation for output sizes (4 d.p. → 0.01 % resolution).
_D4 = Decimal("0.0001")

# Kelly lower clamp: negative Kelly means the strategy has no edge.
_ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# Sizing method enum
# ---------------------------------------------------------------------------


class SizingMethod(str, Enum):
    """Selects the position sizing algorithm.

    Attributes:
        DYNAMIC: Original volatility- and drawdown-adjusted sizer
            (:class:`DynamicSizer`).
        KELLY: Fractional Kelly criterion sizer
            (:class:`KellyFractionalSizer`).
        HYBRID: Kelly combined with ATR volatility adjustment
            (:class:`HybridSizer`).

    Example::

        method = SizingMethod.HYBRID
        if method == SizingMethod.KELLY:
            size = kelly_sizer.calculate_size(...)
    """

    DYNAMIC = "dynamic"
    KELLY = "kelly"
    HYBRID = "hybrid"


# ---------------------------------------------------------------------------
# Configuration models
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


class KellyConfig(BaseSettings):
    """Configurable parameters for the fractional Kelly criterion sizer.

    Attributes:
        kelly_divisor: The denominator applied to the theoretical full-Kelly
            fraction.  ``2`` yields Half-Kelly (recommended for live
            trading); ``4`` yields Quarter-Kelly (more conservative).
            Must be >= 1.
        max_trade_pct: Hard upper clamp for the output fraction, as a
            fraction of equity.  Default 0.10 (10 %) — suitable for
            aggressive agents.  Set lower (e.g. 0.05) for conservative
            agents.
        min_trade_pct: Hard lower clamp.  Default 0.03 (3 %) — positions
            smaller than this are not placed because the fee overhead is
            disproportionate.

    Example::

        # Half-Kelly with aggressive max
        cfg = KellyConfig(kelly_divisor=2, max_trade_pct=Decimal("0.10"))
        sizer = KellyFractionalSizer(config=cfg)

        # Quarter-Kelly conservative
        cfg = KellyConfig(kelly_divisor=4, max_trade_pct=Decimal("0.05"))
    """

    model_config = SettingsConfigDict(
        env_prefix="KELLY_",
        case_sensitive=False,
        extra="ignore",
    )

    kelly_divisor: int = Field(
        default=2,
        ge=1,
        description=(
            "Denominator for the Kelly fraction. "
            "2 = Half-Kelly (recommended), 4 = Quarter-Kelly."
        ),
    )
    max_trade_pct: Decimal = Field(
        default=Decimal("0.10"),
        description="Hard upper clamp on any sized position (0–1).",
    )
    min_trade_pct: Decimal = Field(
        default=Decimal("0.03"),
        description="Hard lower clamp — positions below this are not placed (0–1).",
    )


class HybridConfig(BaseSettings):
    """Configuration for the hybrid Kelly + ATR volatility sizer.

    Attributes:
        kelly_divisor: See :class:`KellyConfig.kelly_divisor`.
        max_trade_pct: Hard upper clamp (default 0.10 = 10 %).
        min_trade_pct: Hard lower clamp (default 0.03 = 3 %).
        target_vol: The long-run target volatility expressed as
            ``atr / close_price``.  When current volatility equals this
            value the Kelly fraction is applied unchanged.  When current
            volatility is higher the position is reduced; when lower it
            is increased (up to ``max_trade_pct``).  Default 0.02 (2 %)
            — a typical daily volatility level for BTC/USDT.

    Example::

        cfg = HybridConfig(
            kelly_divisor=2,
            target_vol=Decimal("0.02"),
            max_trade_pct=Decimal("0.10"),
        )
        sizer = HybridSizer(config=cfg)
    """

    model_config = SettingsConfigDict(
        env_prefix="HYBRID_",
        case_sensitive=False,
        extra="ignore",
    )

    kelly_divisor: int = Field(
        default=2,
        ge=1,
        description=(
            "Denominator for the Kelly fraction. "
            "2 = Half-Kelly (recommended), 4 = Quarter-Kelly."
        ),
    )
    max_trade_pct: Decimal = Field(
        default=Decimal("0.10"),
        description="Hard upper clamp on any sized position (0–1).",
    )
    min_trade_pct: Decimal = Field(
        default=Decimal("0.03"),
        description="Hard lower clamp — positions below this are not placed (0–1).",
    )
    target_vol: Decimal = Field(
        default=Decimal("0.02"),
        description=(
            "Target normalised volatility (atr / close_price). "
            "Position is scaled by target_vol / current_vol."
        ),
    )


# ---------------------------------------------------------------------------
# Dynamic sizer (original)
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


# ---------------------------------------------------------------------------
# Kelly fractional sizer
# ---------------------------------------------------------------------------


class KellyFractionalSizer:
    """Position sizer based on the fractional Kelly criterion.

    The Kelly criterion computes the theoretically optimal fraction of
    bankroll to risk on a bet with known win probability and
    win/loss ratio.  In practice, the full Kelly fraction is too aggressive
    for live trading — position swings are too large and model estimates of
    win rate and payoff are noisy.  Using a *fraction* (Half-Kelly or
    Quarter-Kelly) reduces sizing proportionally, smoothing the equity curve
    at the cost of lower long-run growth rate.

    Formula::

        kelly_fraction = (win_rate * avg_win_loss_ratio - (1 - win_rate))
                         / avg_win_loss_ratio
        position_pct   = clamp(kelly_fraction / kelly_divisor,
                               min_trade_pct, max_trade_pct)

    Edge cases handled without exceptions:
    - ``avg_win_loss_ratio == 0.0`` → undefined; returns ``0.0``.
    - ``win_rate == 0.0`` → full loss; Kelly is ``−1.0``; returns ``0.0``.
    - Negative Kelly fraction → losing strategy; returns ``0.0``.
    - ``win_rate == 1.0``, finite payoff → Kelly equals 1.0, reduced by
      divisor, then clamped to ``max_trade_pct``.

    Args:
        config: Kelly sizer configuration.  Defaults to
            :class:`KellyConfig` (Half-Kelly, 3–10 % bounds).

    Example::

        sizer = KellyFractionalSizer()
        # 55 % win rate, 1.5 average win/loss ratio → Half-Kelly
        size = sizer.calculate_size(win_rate=0.55, avg_win_loss_ratio=1.5)
        # kelly = (0.55*1.5 - 0.45) / 1.5 = 0.375
        # half = 0.375 / 2 = 0.1875 → clamped to 0.10
    """

    def __init__(self, config: KellyConfig | None = None) -> None:
        self._config = config or KellyConfig()
        self._log = logger.bind(component="KellyFractionalSizer")

    # ------------------------------------------------------------------
    # Static helper — pure Kelly fraction (no clamping)
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_kelly_fraction(
        win_rate: float | Decimal,
        avg_win_loss_ratio: float | Decimal,
    ) -> Decimal:
        """Compute the raw full-Kelly fraction without clamping.

        This is a pure helper that can be called independently when
        callers need the theoretical Kelly value (e.g. for diagnostics
        or the hybrid sizer).

        Args:
            win_rate: Historical win rate as a fraction in ``[0, 1]``.
                e.g. ``0.55`` for 55 % of trades that are winners.
            avg_win_loss_ratio: Average winning trade return divided by
                average losing trade return, e.g. ``1.5`` means winners
                are 50 % larger than losers on average.

        Returns:
            The theoretical Kelly fraction as a :class:`Decimal`.
            Returns ``Decimal("0")`` when the ratio is zero (undefined)
            or when the computed fraction is negative (no edge).

        Example::

            fraction = KellyFractionalSizer.calculate_kelly_fraction(
                win_rate=0.55,
                avg_win_loss_ratio=1.5,
            )
            # → Decimal("0.375")
        """
        d_win_rate = Decimal(str(win_rate))
        d_ratio = Decimal(str(avg_win_loss_ratio))

        # Guard: undefined when ratio is zero.
        if d_ratio <= _ZERO:
            return _ZERO

        # Kelly formula: (w * b - (1 - w)) / b
        # where w = win_rate, b = avg_win_loss_ratio
        numerator = d_win_rate * d_ratio - (Decimal("1") - d_win_rate)
        kelly = numerator / d_ratio

        # Negative Kelly → losing strategy, no position.
        if kelly < _ZERO:
            return _ZERO

        return kelly

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def calculate_size(
        self,
        win_rate: float | Decimal,
        avg_win_loss_ratio: float | Decimal,
    ) -> float:
        """Compute the fractional Kelly position size.

        Args:
            win_rate: Historical win rate as a fraction in ``[0, 1]``.
                Values outside ``[0, 1]`` are accepted but will produce
                degenerate Kelly fractions (negative or > 1).
            avg_win_loss_ratio: Average winning trade return divided by
                average losing trade return.  Must be positive.  Zero or
                negative values return ``0.0``.

        Returns:
            Fractional Kelly position size as a ``float`` in
            ``[min_trade_pct, max_trade_pct]``.  Returns ``0.0`` when the
            strategy has no edge (negative or zero Kelly fraction), which
            intentionally falls *below* ``min_trade_pct`` to signal
            "do not trade".

        Example::

            sizer = KellyFractionalSizer(KellyConfig(kelly_divisor=2))
            size = sizer.calculate_size(win_rate=0.55, avg_win_loss_ratio=1.5)
            # kelly = 0.375, half = 0.1875, clamped → 0.10
        """
        kelly = self.calculate_kelly_fraction(win_rate, avg_win_loss_ratio)

        # No edge → do not trade.
        if kelly <= _ZERO:
            self._log.info(
                "kelly_sizer_no_edge",
                win_rate=str(Decimal(str(win_rate))),
                avg_win_loss_ratio=str(Decimal(str(avg_win_loss_ratio))),
                kelly_fraction="0",
            )
            return 0.0

        # Apply fractional divisor.
        divisor = Decimal(str(self._config.kelly_divisor))
        fractional = kelly / divisor

        # Clamp to configured bounds.
        min_size = self._config.min_trade_pct
        max_size = self._config.max_trade_pct

        clamped = fractional.quantize(_D4, ROUND_HALF_UP)
        clamped = max(clamped, min_size)
        clamped = min(clamped, max_size)

        self._log.info(
            "kelly_sizer_result",
            win_rate=str(Decimal(str(win_rate))),
            avg_win_loss_ratio=str(Decimal(str(avg_win_loss_ratio))),
            kelly_fraction=str(kelly.quantize(_D4, ROUND_HALF_UP)),
            kelly_divisor=str(self._config.kelly_divisor),
            fractional=str(fractional.quantize(_D4, ROUND_HALF_UP)),
            clamped=str(clamped),
        )

        return float(clamped)


# ---------------------------------------------------------------------------
# Hybrid sizer (Kelly + ATR volatility adjustment)
# ---------------------------------------------------------------------------


class HybridSizer:
    """Combines fractional Kelly sizing with ATR-based volatility scaling.

    The hybrid approach addresses a key limitation of pure Kelly sizing: the
    Kelly fraction is based on historical trade statistics and does not adapt
    to current market volatility.  A strategy that performed well in a calm
    market might be over-sized during a volatility spike.

    The adjustment multiplies the Kelly fraction by the ratio of a long-run
    target volatility to the current normalised volatility::

        current_vol   = atr / close_price
        position_pct  = kelly_pct * (target_vol / current_vol)

    When ``current_vol == target_vol`` the Kelly fraction is unchanged.
    When ``current_vol > target_vol`` (high-vol regime) the position is
    reduced proportionally.  When ``current_vol < target_vol`` (low-vol
    regime) the position is increased, but still clamped to
    ``max_trade_pct``.

    Fallback behaviour (safe by default):
    - ``atr == 0`` or ``close_price == 0`` → volatility adjustment is
      skipped; raw fractional Kelly is returned (no division by zero).
    - Negative Kelly → ``0.0`` returned (no trade).

    Args:
        config: Hybrid sizer configuration.  Defaults to
            :class:`HybridConfig` (Half-Kelly, 3–10 % bounds, 2 % target vol).

    Example::

        sizer = HybridSizer()
        size = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=1200.0,
            close_price=42000.0,
        )
        # current_vol = 1200/42000 ≈ 0.0286 (> 0.02 target)
        # kelly = 0.1875 (half of 0.375)
        # adjusted = 0.1875 * (0.02 / 0.0286) ≈ 0.131 → clamped to 0.10
    """

    def __init__(self, config: HybridConfig | None = None) -> None:
        self._config = config or HybridConfig()
        self._log = logger.bind(component="HybridSizer")

    def calculate_size(
        self,
        win_rate: float | Decimal,
        avg_win_loss_ratio: float | Decimal,
        atr: float | Decimal,
        close_price: float | Decimal,
    ) -> float:
        """Compute the ATR-adjusted Kelly position size.

        Args:
            win_rate: Historical win rate as a fraction in ``[0, 1]``.
            avg_win_loss_ratio: Average winning trade return divided by
                average losing trade return.  Must be positive.
            atr: Current Average True Range for the trading pair.  Zero or
                negative values disable the volatility adjustment.
            close_price: Current close price of the trading pair.  Zero or
                negative values disable the volatility adjustment.

        Returns:
            Hybrid position size as a ``float`` in
            ``[min_trade_pct, max_trade_pct]``.  Returns ``0.0`` when the
            strategy has no edge (negative Kelly fraction), bypassing the
            ``min_trade_pct`` clamp intentionally.

        Example::

            sizer = HybridSizer(HybridConfig(kelly_divisor=2, target_vol=Decimal("0.02")))
            size = sizer.calculate_size(0.55, 1.5, atr=840.0, close_price=42000.0)
            # current_vol = 840/42000 = 0.02 (equal to target) → no vol adjustment
            # kelly = 0.375, half = 0.1875 → clamped to 0.10
        """
        # Step 1: Compute fractional Kelly.
        kelly = KellyFractionalSizer.calculate_kelly_fraction(win_rate, avg_win_loss_ratio)

        # No edge → do not trade.
        if kelly <= _ZERO:
            self._log.info(
                "hybrid_sizer_no_edge",
                win_rate=str(Decimal(str(win_rate))),
                avg_win_loss_ratio=str(Decimal(str(avg_win_loss_ratio))),
            )
            return 0.0

        divisor = Decimal(str(self._config.kelly_divisor))
        fractional_kelly = kelly / divisor

        d_atr = Decimal(str(atr))
        d_close = Decimal(str(close_price))

        # Step 2: Compute current normalised volatility and apply adjustment.
        if d_atr > _ZERO and d_close > _ZERO:
            current_vol = d_atr / d_close
            target_vol = self._config.target_vol

            if current_vol > _ZERO:
                vol_multiplier = target_vol / current_vol
                adjusted = fractional_kelly * vol_multiplier
                self._log.debug(
                    "hybrid_sizer_vol_adjustment",
                    current_vol=f"{float(current_vol):.6f}",
                    target_vol=str(target_vol),
                    vol_multiplier=f"{float(vol_multiplier):.4f}",
                    kelly_fractional=str(fractional_kelly.quantize(_D4, ROUND_HALF_UP)),
                    adjusted=str(adjusted.quantize(_D4, ROUND_HALF_UP)),
                )
            else:
                adjusted = fractional_kelly
                self._log.debug(
                    "hybrid_sizer_vol_skipped",
                    reason="computed current_vol is zero",
                )
        else:
            adjusted = fractional_kelly
            self._log.debug(
                "hybrid_sizer_vol_skipped",
                atr=str(d_atr),
                close_price=str(d_close),
                reason="non-positive ATR or close_price",
            )

        # Step 3: Clamp.
        min_size = self._config.min_trade_pct
        max_size = self._config.max_trade_pct

        clamped = adjusted.quantize(_D4, ROUND_HALF_UP)
        clamped = max(clamped, min_size)
        clamped = min(clamped, max_size)

        self._log.info(
            "hybrid_sizer_result",
            win_rate=str(Decimal(str(win_rate))),
            avg_win_loss_ratio=str(Decimal(str(avg_win_loss_ratio))),
            kelly_full=str(kelly.quantize(_D4, ROUND_HALF_UP)),
            kelly_fractional=str(fractional_kelly.quantize(_D4, ROUND_HALF_UP)),
            atr=str(d_atr),
            close_price=str(d_close),
            final_size_pct=str(clamped),
        )

        return float(clamped)
