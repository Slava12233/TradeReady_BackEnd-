"""Veto pipeline for trade signals at the portfolio-risk layer.

This module implements a sequential gate-checking pipeline that takes a
proposed :class:`TradeSignal` and a :class:`~agent.strategies.risk.RiskAssessment`
and decides whether to approve the trade, resize it, or veto it entirely.

The pipeline runs six checks in strict priority order and short-circuits on
the first VETOED outcome.  A RESIZED outcome does *not* short-circuit — it
adjusts the size and continues to subsequent checks so that a resized trade
still passes the remaining gates.

Pipeline check order:
    1. Risk verdict is HALT           → VETOED  (hard stop, no trading)
    2. Signal confidence < 0.5        → VETOED  (low conviction)
    3. Exceeds max portfolio exposure  → RESIZED (cap at remaining capacity)
    4. Same-sector concentration       → VETOED  (≥ 2 existing positions in sector)
    5. Recent drawdown > 3 %           → RESIZED (halve position size)
    6. All checks passed               → APPROVED

Financial values (size fractions) are handled as :class:`decimal.Decimal`
internally and converted to ``float`` only for the final output model to
keep the JSON serialisation surface simple.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from agent.strategies.risk.risk_agent import (
    _QUOTE_SUFFIXES,  # noqa: PLC2701 — intentional same-package access
    _SECTOR_MAP,  # noqa: PLC2701 — intentional same-package access
    _SYMBOL_RE,  # noqa: PLC2701 — intentional same-package access
    RiskAssessment,
    RiskConfig,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Drawdown fraction above which position size is halved.
# 3 % == 0.03 expressed as Decimal for precise comparison.
_DRAWDOWN_RESIZE_THRESHOLD = Decimal("0.03")

# Minimum confidence required to proceed with a trade.
_MIN_CONFIDENCE = 0.5

# Number of existing same-sector positions that triggers a correlation veto.
# The check vetoes when there are *2 or more* existing positions (strictly
# greater than or equal to max_correlated_positions from RiskConfig, default 2).
_CORRELATION_VETO_COUNT = 2

# Quantisation used for adjusted sizes (4 decimal places → 0.01 % precision).
_D4 = Decimal("0.0001")


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class TradeSignal(BaseModel):
    """A proposed trade signal entering the veto pipeline.

    This model is scoped to the risk / veto layer and is distinct from the
    LLM output :class:`agent.models.trade_signal.TradeSignal`.  It carries
    the minimal information the pipeline needs to evaluate a trade.

    Attributes:
        symbol: Trading pair in uppercase, e.g. ``"BTCUSDT"``.
        side: Trade direction — ``"buy"`` or ``"sell"``.
        size_pct: Desired allocation as a fraction of equity in ``(0, 1]``.
            E.g. ``0.05`` for 5 %.
        confidence: Model or strategy confidence in the signal, ``[0, 1]``.
            Values below 0.5 are rejected by check 2.

    Example::

        signal = TradeSignal(
            symbol="SOLUSDT",
            side="buy",
            size_pct=0.08,
            confidence=0.72,
        )
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading pair symbol, e.g. 'BTCUSDT'.")
    side: str = Field(
        ...,
        pattern="^(buy|sell)$",
        description="Trade direction: 'buy' or 'sell'.",
    )
    size_pct: float = Field(
        ...,
        gt=0.0,
        le=1.0,
        description="Desired allocation as a fraction of equity (0–1].",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Strategy or model confidence in the signal (0–1).",
    )


class VetoDecision(BaseModel):
    """Result of running a :class:`TradeSignal` through the :class:`VetoPipeline`.

    Attributes:
        action: Final decision for the trade.

            * ``"APPROVED"`` — proceed at the original (or previously resized)
              size.
            * ``"RESIZED"`` — proceed, but use ``adjusted_size_pct`` instead of
              ``original_size_pct``.
            * ``"VETOED"``  — do not execute this trade.

        original_size_pct: The size fraction as requested in the signal.
            Always equal to :attr:`TradeSignal.size_pct`.
        adjusted_size_pct: The size fraction the pipeline recommends using.
            For ``"APPROVED"`` this equals ``original_size_pct``.  For
            ``"RESIZED"`` it is lower than ``original_size_pct``.  For
            ``"VETOED"`` it is ``0.0``.
        reason: Human-readable explanation of the decision, identifying which
            check triggered it.  Intended for logging and debugging.
        scale_factor: Position-size multiplier propagated from the
            :class:`~agent.strategies.risk.RiskAssessment` (computed by the
            agent's :class:`~agent.strategies.risk.DrawdownProfile`).
            Callers should apply this multiplier to ``adjusted_size_pct``
            before computing the final order quantity::

                final_qty = equity * adjusted_size_pct * scale_factor

            ``1.0`` when no drawdown scaling is required.  ``0.0`` when the
            risk verdict was ``HALT`` (trade is fully suppressed regardless
            of the pipeline action).

    Example::

        decision = pipeline.evaluate(signal, assessment)
        if decision.action == "VETOED":
            logger.info("trade_vetoed", reason=decision.reason)
        elif decision.action == "RESIZED":
            effective_size = decision.adjusted_size_pct * decision.scale_factor
            qty = equity * Decimal(str(effective_size))
    """

    model_config = ConfigDict(frozen=True)

    action: str = Field(
        ...,
        pattern="^(APPROVED|RESIZED|VETOED)$",
        description="Pipeline decision: APPROVED, RESIZED, or VETOED.",
    )
    original_size_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Requested allocation fraction from the signal.",
    )
    adjusted_size_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Recommended allocation fraction after pipeline adjustments.",
    )
    reason: str = Field(
        ...,
        description="Human-readable explanation of why this decision was reached.",
    )
    scale_factor: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Position-size multiplier from the DrawdownProfile. "
            "Callers multiply adjusted_size_pct by this value to get the "
            "effective allocation. 0.0 when verdict is HALT."
        ),
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class VetoPipeline:
    """Sequential gate-checking pipeline for trade signal veto decisions.

    Runs up to six checks in priority order.  The pipeline short-circuits on
    the first VETOED result; RESIZED results carry forward an adjusted size
    into subsequent checks.

    Args:
        config: Risk configuration thresholds.  When not supplied, a default
            :class:`~agent.strategies.risk.RiskConfig` is constructed.
        existing_positions: List of currently open position dicts as returned
            by the platform SDK ``get_positions()`` or the REST
            ``/portfolio/positions`` endpoint.  Each dict must contain at
            minimum a ``"symbol"`` key.  Defaults to an empty list.

    Example::

        pipeline = VetoPipeline(
            config=RiskConfig(),
            existing_positions=[{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}],
        )
        decision = pipeline.evaluate(signal, assessment)
    """

    def __init__(
        self,
        config: RiskConfig | None = None,
        existing_positions: list[dict[str, Any]] | None = None,
    ) -> None:
        self._config = config or RiskConfig()
        self._positions: list[dict[str, Any]] = existing_positions or []
        self._log = logger.bind(component="VetoPipeline")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def evaluate(
        self,
        signal: TradeSignal,
        risk_assessment: RiskAssessment,
    ) -> VetoDecision:
        """Run the signal through all pipeline checks and return a decision.

        Checks are evaluated in the order documented in the module docstring.
        The first VETOED outcome short-circuits the pipeline.  RESIZED
        outcomes reduce ``current_size`` and continue to remaining checks
        so that the final approved size satisfies *all* non-veto constraints.

        Args:
            signal: The proposed trade to evaluate.
            risk_assessment: A current :class:`~agent.strategies.risk.RiskAssessment`
                produced by :meth:`~agent.strategies.risk.RiskAgent.assess`.

        Returns:
            A frozen :class:`VetoDecision` with the pipeline's outcome.
        """
        original_size = Decimal(str(signal.size_pct))
        current_size = original_size
        # Propagate the DrawdownProfile scale_factor from the assessment so
        # downstream callers can apply it without re-computing it.
        scale_factor: float = risk_assessment.scale_factor

        self._log.info(
            "veto_pipeline_start",
            symbol=signal.symbol,
            side=signal.side,
            size_pct=str(original_size),
            confidence=signal.confidence,
            verdict=risk_assessment.verdict,
            scale_factor=f"{scale_factor:.4f}",
        )

        # ------------------------------------------------------------------
        # Check 1: Risk verdict is HALT — hard stop, no new trades.
        # ------------------------------------------------------------------
        if risk_assessment.verdict == "HALT":
            return self._vetoed(
                original_size=original_size,
                scale_factor=scale_factor,
                reason=(
                    "Risk verdict is HALT: "
                    f"{risk_assessment.action or 'daily loss limit exceeded'}. "
                    "No new trades permitted until the next session."
                ),
            )

        # ------------------------------------------------------------------
        # Check 2: Confidence below minimum threshold.
        # ------------------------------------------------------------------
        if signal.confidence < _MIN_CONFIDENCE:
            return self._vetoed(
                original_size=original_size,
                scale_factor=scale_factor,
                reason=(
                    f"Signal confidence {signal.confidence:.2f} is below the "
                    f"minimum threshold of {_MIN_CONFIDENCE:.2f}. "
                    "Low-conviction signals are rejected to avoid noise trades."
                ),
            )

        # ------------------------------------------------------------------
        # Check 3: Adding this position would exceed max portfolio exposure.
        # ------------------------------------------------------------------
        current_exposure = Decimal(str(risk_assessment.total_exposure_pct))
        max_exposure = self._config.max_portfolio_exposure
        remaining_capacity = max_exposure - current_exposure

        if remaining_capacity <= Decimal("0"):
            return self._vetoed(
                original_size=original_size,
                scale_factor=scale_factor,
                reason=(
                    f"Portfolio already at or above max exposure "
                    f"({float(current_exposure):.1%} >= {float(max_exposure):.1%}). "
                    "No additional positions can be opened."
                ),
            )

        if current_size > remaining_capacity:
            # Cap at remaining capacity, quantised to 4 d.p.
            capped_size = remaining_capacity.quantize(_D4, ROUND_HALF_UP)
            if capped_size <= Decimal("0"):
                return self._vetoed(
                    original_size=original_size,
                    scale_factor=scale_factor,
                    reason=(
                        f"Remaining portfolio capacity "
                        f"({float(remaining_capacity):.4%}) rounds to zero. "
                        "Veto to avoid a negligible order."
                    ),
                )
            self._log.info(
                "veto_check3_resize",
                original=str(current_size),
                capped=str(capped_size),
                remaining_capacity=str(remaining_capacity),
            )
            reason_so_far = (
                f"Resized from {float(current_size):.1%} to "
                f"{float(capped_size):.1%} to keep portfolio exposure within "
                f"{float(max_exposure):.1%} limit (currently at "
                f"{float(current_exposure):.1%})."
            )
            current_size = capped_size
        else:
            reason_so_far = ""

        # ------------------------------------------------------------------
        # Check 4: Same-sector correlation — veto if 2+ existing positions
        # are already in the same inferred sector as the proposed symbol.
        # ------------------------------------------------------------------
        signal_sector = self._get_sector(signal.symbol)
        sector_count = self._count_sector_positions(signal_sector)

        if sector_count >= _CORRELATION_VETO_COUNT:
            return self._vetoed(
                original_size=original_size,
                scale_factor=scale_factor,
                reason=(
                    f"Correlation risk: {sector_count} existing position(s) "
                    f"already in the '{signal_sector}' sector. "
                    f"Adding {signal.symbol} would create excessive concentration "
                    f"(limit: {_CORRELATION_VETO_COUNT - 1} existing positions per sector)."
                ),
            )

        # ------------------------------------------------------------------
        # Check 5: Recent drawdown > 3 % — halve the position size.
        # ------------------------------------------------------------------
        drawdown = Decimal(str(risk_assessment.drawdown_pct))

        if drawdown > _DRAWDOWN_RESIZE_THRESHOLD:
            halved = (current_size / Decimal("2")).quantize(_D4, ROUND_HALF_UP)
            # Clamp to the configured minimum (0.01 of max_single_position)
            # to avoid a zero or negative size.
            min_size = (self._config.max_single_position * Decimal("0.1")).quantize(
                _D4, ROUND_HALF_UP
            )
            halved = max(halved, min_size)
            self._log.info(
                "veto_check5_resize",
                drawdown=str(drawdown),
                before=str(current_size),
                after=str(halved),
            )
            drawdown_reason = (
                f"Drawdown of {float(drawdown):.2%} exceeds the "
                f"{float(_DRAWDOWN_RESIZE_THRESHOLD):.0%} threshold; "
                f"position halved from {float(current_size):.1%} to "
                f"{float(halved):.1%}."
            )
            current_size = halved
            reason_so_far = (
                f"{reason_so_far}  {drawdown_reason}".strip()
                if reason_so_far
                else drawdown_reason
            )

        # ------------------------------------------------------------------
        # Check 6: All checks passed (possibly with size adjustments).
        # ------------------------------------------------------------------
        if current_size != original_size:
            # At least one RESIZED adjustment was made.
            return VetoDecision(
                action="RESIZED",
                original_size_pct=float(original_size),
                adjusted_size_pct=float(current_size),
                reason=reason_so_far or "Size adjusted within pipeline.",
                scale_factor=scale_factor,
            )

        return VetoDecision(
            action="APPROVED",
            original_size_pct=float(original_size),
            adjusted_size_pct=float(original_size),
            reason=(
                f"All pipeline checks passed. "
                f"Trade {signal.symbol} {signal.side} at "
                f"{float(original_size):.1%} approved."
            ),
            scale_factor=scale_factor,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _vetoed(original_size: Decimal, reason: str, scale_factor: float = 1.0) -> VetoDecision:
        """Construct a VETOED :class:`VetoDecision`.

        Args:
            original_size: The originally requested size fraction.
            reason: Human-readable explanation of why the trade was vetoed.
            scale_factor: DrawdownProfile multiplier propagated from the
                :class:`~agent.strategies.risk.RiskAssessment`.  Included for
                audit completeness even when the trade is vetoed.

        Returns:
            A frozen :class:`VetoDecision` with ``action="VETOED"`` and
            ``adjusted_size_pct=0.0``.
        """
        return VetoDecision(
            action="VETOED",
            original_size_pct=float(original_size),
            adjusted_size_pct=0.0,
            reason=reason,
            scale_factor=scale_factor,
        )

    def _get_sector(self, symbol: str) -> str:
        """Infer the sector for a trading-pair symbol.

        Args:
            symbol: Upper-case trading pair, e.g. ``"SOLUSDT"``.

        Returns:
            Sector string from ``_SECTOR_MAP``, or ``"other"`` when the base
            asset is not in the map.
        """
        clean = symbol.upper()
        if not _SYMBOL_RE.match(clean):
            return "other"
        base = self._extract_base_asset(clean)
        return _SECTOR_MAP.get(base, "other")

    def _count_sector_positions(self, sector: str) -> int:
        """Count how many existing positions belong to the given sector.

        Args:
            sector: Sector tag to count (e.g. ``"large_cap"``).

        Returns:
            Number of open positions whose inferred sector matches.
        """
        count = 0
        for pos in self._positions:
            pos_symbol = str(pos.get("symbol", "")).upper()
            if self._get_sector(pos_symbol) == sector:
                count += 1
        return count

    @staticmethod
    def _extract_base_asset(symbol: str) -> str:
        """Strip the quote-asset suffix from a symbol to get the base asset.

        Args:
            symbol: Upper-case trading pair symbol, e.g. ``"BTCUSDT"``.

        Returns:
            Base asset string, e.g. ``"BTC"``.  Returns the full symbol if
            no known suffix matches.
        """
        for suffix in _QUOTE_SUFFIXES:
            if symbol.endswith(suffix) and len(symbol) > len(suffix):
                return symbol[: -len(suffix)]
        return symbol
