"""Portfolio-level risk monitoring agent for the AiTradingAgent strategies layer.

This module provides portfolio-level exposure, drawdown, and correlation
checks that complement — but do not duplicate — the platform's built-in
per-order risk manager (``src/risk/manager.py``).

The platform already enforces per-order constraints through an 8-step
validation chain:
    * Account active, daily loss limit, rate limit
    * Min/max order size, position size, max open orders, sufficient balance

This ``RiskAgent`` operates at the aggregate portfolio level and answers two
questions the platform does not ask:

1. **``assess()``** — Given the current portfolio snapshot, what is the overall
   risk state? Should the strategy continue normally, reduce exposure, or halt
   all new trades?

2. **``check_trade()``** — Before sending a proposed signal to the order engine,
   should the agent trade it at all, and at what adjusted size?

Verdict logic (in priority order):
    * ``"HALT"``   — daily PnL loss exceeds ``daily_loss_halt`` threshold.
    * ``"REDUCE"`` — portfolio drawdown exceeds ``max_drawdown_trigger``.
    * ``"OK"``     — everything within acceptable bounds.

Correlation risk is a qualitative measure based on the count of open positions
whose symbols share a common base-asset sector prefix.  It does not require an
external sector database; it infers sector proximity from symbol-name patterns
(e.g. BTC/ETH = large-cap, SOL/AVAX/NEAR = L1 alt-coins).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Sector heuristics
# ---------------------------------------------------------------------------

# Mapping of symbol prefixes to a sector tag used for correlation detection.
# Only the base-asset prefix (e.g. "BTC" from "BTCUSDT") is matched.
_SECTOR_MAP: dict[str, str] = {
    # Large-cap: BTC, ETH
    "BTC": "large_cap",
    "ETH": "large_cap",
    # L1 smart-contract platforms
    "SOL": "l1_platform",
    "AVAX": "l1_platform",
    "NEAR": "l1_platform",
    "FTM": "l1_platform",
    "ONE": "l1_platform",
    "EGLD": "l1_platform",
    # DeFi / DEX tokens
    "UNI": "defi",
    "AAVE": "defi",
    "CAKE": "defi",
    "SUSHI": "defi",
    "COMP": "defi",
    "CRV": "defi",
    "MKR": "defi",
    # Layer-2 / scaling
    "MATIC": "l2_scaling",
    "OP": "l2_scaling",
    "ARB": "l2_scaling",
    "LRC": "l2_scaling",
    # Exchange tokens
    "BNB": "exchange_token",
    "FTT": "exchange_token",
    "OKB": "exchange_token",
    "HT": "exchange_token",
    # Meme / dog coins
    "DOGE": "meme",
    "SHIB": "meme",
    "FLOKI": "meme",
    "PEPE": "meme",
}

# Quote suffixes to strip when extracting the base asset from a symbol.
_QUOTE_SUFFIXES: tuple[str, ...] = ("USDT", "BUSD", "USDC", "BTC", "ETH", "BNB")

# Regex matching only-uppercase alphanumeric symbols to prevent injection.
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}$")

# Quantisation for Decimal display (8 decimal places).
_D8 = Decimal("0.00000001")


# ---------------------------------------------------------------------------
# Drawdown profile — configurable position-size multipliers per drawdown range
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DrawdownTier:
    """A single drawdown tier mapping a drawdown threshold to a size multiplier.

    Attributes:
        threshold: Drawdown fraction at which this tier activates (inclusive
            lower bound).  E.g. ``0.15`` means "when drawdown >= 15 %".
        multiplier: Position size multiplier applied while in this tier.
            E.g. ``0.75`` means reduce position size to 75 % of base.

    Example::

        tier = DrawdownTier(threshold=0.15, multiplier=0.75)
    """

    threshold: float
    """Drawdown fraction lower bound (0–1) for this tier."""

    multiplier: float
    """Size multiplier (0–1] applied when drawdown is at or above threshold."""


@dataclass(frozen=True)
class DrawdownProfile:
    """Per-agent configurable drawdown response profile.

    Maps portfolio drawdown depth to a position-size scale factor via an
    ordered list of :class:`DrawdownTier` entries.  The active tier is the
    **highest threshold** that is still less than or equal to the current
    drawdown — i.e. tiers are evaluated from most restrictive to least, and
    the first matching tier (highest threshold ≤ drawdown) wins.

    Tiers should be provided in *ascending* threshold order; ``__post_init__``
    sorts them so callers need not worry about ordering.

    Attributes:
        name: Human-readable profile name (e.g. ``"AGGRESSIVE"``).
        tiers: Ordered list of :class:`DrawdownTier` entries.  The first tier
            must have ``threshold=0.0`` so there is always a matching tier.
            Sorted ascending by threshold on construction.

    Example::

        profile = DrawdownProfile(
            name="custom",
            tiers=[
                DrawdownTier(threshold=0.0,  multiplier=1.0),
                DrawdownTier(threshold=0.10, multiplier=0.75),
                DrawdownTier(threshold=0.20, multiplier=0.5),
                DrawdownTier(threshold=0.30, multiplier=0.25),
            ],
        )
        factor = profile.scale_factor(drawdown_pct=0.15)  # → 0.75
    """

    name: str
    """Profile identifier, e.g. ``"AGGRESSIVE"``, ``"MODERATE"``, ``"CONSERVATIVE"``."""

    tiers: tuple[DrawdownTier, ...]
    """Ordered drawdown tiers (ascending threshold)."""

    def __post_init__(self) -> None:
        """Validate and sort tiers after construction.

        Raises:
            ValueError: If no tiers are provided or no tier has threshold 0.0.
        """
        if not self.tiers:
            raise ValueError("DrawdownProfile requires at least one tier.")
        # Re-sort via object.__setattr__ because the dataclass is frozen.
        sorted_tiers = tuple(sorted(self.tiers, key=lambda t: t.threshold))
        object.__setattr__(self, "tiers", sorted_tiers)
        if sorted_tiers[0].threshold != 0.0:
            raise ValueError(
                "The first DrawdownTier (after sorting) must have threshold=0.0 "
                "to ensure a matching tier always exists."
            )

    def scale_factor(self, drawdown_pct: float) -> float:
        """Return the position-size multiplier for the given drawdown fraction.

        Iterates tiers in *descending* threshold order and returns the
        multiplier of the first tier whose threshold does not exceed
        ``drawdown_pct``.  Because the base tier always has threshold 0.0,
        this always returns a valid multiplier.

        Args:
            drawdown_pct: Current portfolio drawdown as a fraction in [0, ∞).
                Values > 1.0 are clamped to the most restrictive tier.

        Returns:
            A multiplier in (0, 1] — 1.0 when drawdown is within the first
            tier, lower values as drawdown deepens.

        Example::

            profile = AGGRESSIVE_PROFILE
            # Drawdown 20 % falls in the 15–25 % tier → 0.75×
            assert profile.scale_factor(0.20) == 0.75
        """
        # Evaluate from highest threshold downward so the first match is the
        # most-restrictive applicable tier.
        for tier in reversed(self.tiers):
            if drawdown_pct >= tier.threshold:
                return tier.multiplier
        # Should never be reached because tier[0].threshold == 0.0 and
        # drawdown_pct >= 0.0 always. Return 1.0 as a safe fallback.
        return 1.0  # pragma: no cover


# ---------------------------------------------------------------------------
# Preset profiles
# ---------------------------------------------------------------------------

#: Aggressive profile — for Momentum and Evolved strategies.
#: Full size at <15 %, tapering to 0.25× at >40 % drawdown.
AGGRESSIVE_PROFILE = DrawdownProfile(
    name="AGGRESSIVE",
    tiers=(
        DrawdownTier(threshold=0.00, multiplier=1.00),
        DrawdownTier(threshold=0.15, multiplier=0.75),
        DrawdownTier(threshold=0.25, multiplier=0.50),
        DrawdownTier(threshold=0.40, multiplier=0.25),
    ),
)

#: Moderate profile — for Balanced and Regime strategies.
#: Full size at <10 %, tapering to 0.25× at >30 % drawdown.
MODERATE_PROFILE = DrawdownProfile(
    name="MODERATE",
    tiers=(
        DrawdownTier(threshold=0.00, multiplier=1.00),
        DrawdownTier(threshold=0.10, multiplier=0.75),
        DrawdownTier(threshold=0.20, multiplier=0.50),
        DrawdownTier(threshold=0.30, multiplier=0.25),
    ),
)

#: Conservative profile — tightest drawdown response.
#: Full size only at <5 %, dropping to 0.25× at >10 % drawdown.
CONSERVATIVE_PROFILE = DrawdownProfile(
    name="CONSERVATIVE",
    tiers=(
        DrawdownTier(threshold=0.00, multiplier=1.00),
        DrawdownTier(threshold=0.05, multiplier=0.50),
        DrawdownTier(threshold=0.10, multiplier=0.25),
    ),
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class RiskConfig(BaseSettings):
    """Configurable risk thresholds for the portfolio-level risk agent.

    All thresholds are expressed as fractions (0–1) of portfolio equity unless
    stated otherwise.  Defaults represent conservative settings appropriate for
    an automated trading bot.

    Attributes:
        max_portfolio_exposure: Maximum fraction of equity that may be held in
            non-cash positions simultaneously (default 0.30 = 30 %).
        max_single_position: Maximum fraction of equity in any single position
            (default 0.10 = 10 %).
        max_drawdown_trigger: Drawdown fraction at which the agent emits a
            ``"REDUCE"`` verdict (default 0.05 = 5 %).
        max_correlated_positions: Maximum number of open positions in the same
            inferred sector before ``correlation_risk`` is rated ``"high"``
            (default 2).
        daily_loss_halt: Daily PnL loss fraction at which the agent emits a
            ``"HALT"`` verdict (default 0.03 = 3 %).
        drawdown_profile: Per-agent :class:`DrawdownProfile` that determines
            how position sizes are scaled as drawdown deepens.  Defaults to
            :data:`MODERATE_PROFILE` (balanced, suits most strategies).
            Pass :data:`AGGRESSIVE_PROFILE` for momentum/evolved strategies or
            :data:`CONSERVATIVE_PROFILE` for risk-averse strategies.

    Example::

        cfg = RiskConfig(
            max_drawdown_trigger=Decimal("0.08"),
            drawdown_profile=AGGRESSIVE_PROFILE,
        )
    """

    model_config = SettingsConfigDict(
        env_prefix="RISK_",
        case_sensitive=False,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    max_portfolio_exposure: Decimal = Field(
        default=Decimal("0.30"),
        description="Max fraction of equity in open positions (0–1).",
    )
    max_single_position: Decimal = Field(
        default=Decimal("0.10"),
        description="Max fraction of equity in any single position (0–1).",
    )
    max_drawdown_trigger: Decimal = Field(
        default=Decimal("0.05"),
        description="Drawdown fraction that triggers a REDUCE verdict.",
    )
    max_correlated_positions: int = Field(
        default=2,
        ge=1,
        description="Max same-sector open positions before correlation_risk is high.",
    )
    daily_loss_halt: Decimal = Field(
        default=Decimal("0.03"),
        description="Daily loss fraction (of equity) that triggers a HALT verdict.",
    )
    drawdown_profile: DrawdownProfile = Field(
        default=MODERATE_PROFILE,
        description=(
            "Per-agent drawdown profile controlling position-size scaling as "
            "drawdown deepens.  Choose AGGRESSIVE_PROFILE, MODERATE_PROFILE "
            "(default), or CONSERVATIVE_PROFILE — or supply a custom "
            "DrawdownProfile instance."
        ),
        # exclude=True prevents pydantic-settings from attempting to read
        # DrawdownProfile from environment variables (it is always set
        # programmatically via the constructor or default).
        exclude=True,
    )


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class RiskAssessment(BaseModel):
    """Snapshot of the portfolio's current risk posture.

    Produced by :meth:`RiskAgent.assess`.  All financial figures are
    ``Decimal`` to preserve precision; ratio fields are plain ``float`` for
    JSON-friendly output.

    Attributes:
        total_exposure_pct: Fraction of equity currently committed to open
            positions (sum of position market values divided by total equity).
            Value in range [0.0, 1.0]; may temporarily exceed 1.0 if equity
            dropped below position cost basis.
        max_single_position_pct: Largest single position as a fraction of
            total equity.
        drawdown_pct: Percentage decline from the peak equity seen during this
            session (0.0 = at peak, 0.10 = 10 % below peak).
        correlation_risk: Qualitative correlation level based on the number of
            open positions sharing a common sector.  One of ``"low"``,
            ``"medium"``, or ``"high"``.
        verdict: Agent's overall risk verdict.  One of:
            * ``"OK"``     — all metrics within bounds; proceed normally.
            * ``"REDUCE"`` — drawdown trigger exceeded; cut new position sizes.
            * ``"HALT"``   — daily loss limit hit; stop all new trades.
        action: Optional human-readable action recommendation such as
            ``"close position in SOLUSDT"`` or ``None`` when no specific action
            is required.
        equity: Current total portfolio equity (USDT value, ``Decimal``).
        peak_equity: Highest equity seen since agent initialisation (used to
            compute drawdown).

    Example::

        assessment = await agent.assess(portfolio, positions, recent_pnl)
        if assessment.verdict == "HALT":
            logger.warning("trading_halted", reason=assessment.action)
    """

    model_config = ConfigDict(frozen=True)

    total_exposure_pct: float = Field(
        ...,
        ge=0.0,
        description="Fraction of equity in open positions.",
    )
    max_single_position_pct: float = Field(
        ...,
        ge=0.0,
        description="Largest single position as fraction of equity.",
    )
    drawdown_pct: float = Field(
        ...,
        ge=0.0,
        description="Peak-to-current equity drawdown fraction.",
    )
    correlation_risk: str = Field(
        ...,
        pattern="^(low|medium|high)$",
        description="Qualitative correlation level: low, medium, or high.",
    )
    verdict: str = Field(
        ...,
        pattern="^(OK|REDUCE|HALT)$",
        description="Risk verdict: OK, REDUCE, or HALT.",
    )
    action: str | None = Field(
        default=None,
        description="Optional recommended action, e.g. 'close position in SOLUSDT'.",
    )
    equity: Decimal = Field(
        ...,
        description="Current total equity in USDT.",
    )
    peak_equity: Decimal = Field(
        ...,
        description="Highest equity recorded since agent init (drawdown baseline).",
    )
    scale_factor: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Position-size multiplier derived from the agent's DrawdownProfile. "
            "1.0 when drawdown is within the base tier; lower values as drawdown "
            "deepens according to the profile thresholds. "
            "Callers (e.g. VetoPipeline, DynamicSizer) should multiply the "
            "intended position size by this factor before placing orders."
        ),
    )


class TradeApproval(BaseModel):
    """Result of a pre-trade size and exposure check.

    Produced by :meth:`RiskAgent.check_trade`.  The agent may approve the
    trade at the original size, approve at a reduced size, or veto entirely.

    Attributes:
        approved: ``True`` if the agent allows the trade to proceed (possibly
            at a reduced size), ``False`` to veto.
        adjusted_size_pct: The recommended position size as a fraction of
            equity.  Equal to the proposed size when no adjustment was needed,
            or lower when the agent reduced it to stay within limits.  Always
            0.0 when ``approved`` is ``False``.
        reason: Human-readable explanation of the approval decision, including
            which limit was approached or breached.

    Example::

        approval = await agent.check_trade(signal, portfolio)
        if not approval.approved:
            logger.info("trade_vetoed", reason=approval.reason)
        else:
            qty = equity * Decimal(str(approval.adjusted_size_pct))
    """

    model_config = ConfigDict(frozen=True)

    approved: bool = Field(..., description="Whether the trade is approved.")
    adjusted_size_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Recommended size as fraction of equity (0.0 if vetoed).",
    )
    reason: str = Field(..., description="Explanation of the approval decision.")


# ---------------------------------------------------------------------------
# Risk agent
# ---------------------------------------------------------------------------


class RiskAgent:
    """Portfolio-level risk monitor.

    Tracks peak equity across calls to :meth:`assess` so drawdown is always
    computed relative to the highest equity seen since the agent was
    instantiated — not just the starting balance.

    Args:
        config: Risk thresholds.  Pass a customised :class:`RiskConfig` to
            override any default.
        sdk_client: Optional SDK client instance.  Currently unused by the
            risk calculations but accepted for future extension (e.g. fetching
            live balances on demand).

    Example::

        agent = RiskAgent(config=RiskConfig())
        assessment = await agent.assess(portfolio, positions, recent_pnl)
        approval = await agent.check_trade(signal, portfolio)
    """

    def __init__(
        self,
        config: RiskConfig,
        sdk_client: object | None = None,
        drawdown_profile: DrawdownProfile | None = None,
    ) -> None:
        self._config = config
        self._sdk_client = sdk_client
        self._peak_equity: Decimal = Decimal("0")
        self._log = logger.bind(component="RiskAgent")
        # DrawdownProfile precedence: explicit arg → config field → MODERATE default.
        self._drawdown_profile: DrawdownProfile = (
            drawdown_profile or config.drawdown_profile
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def assess(
        self,
        portfolio: dict[str, Any],
        positions: list[dict[str, Any]],
        recent_pnl: Decimal,
    ) -> RiskAssessment:
        """Assess the current portfolio-level risk posture.

        Computes exposure, drawdown, and correlation metrics from the
        portfolio and position data, then returns a :class:`RiskAssessment`
        with an actionable verdict.

        The platform's per-order checks (position limit, daily loss circuit-
        breaker, etc.) are NOT duplicated here.  This method adds higher-level
        aggregate portfolio checks on top.

        Args:
            portfolio: Portfolio summary dict as returned by the SDK
                ``get_performance()`` or the REST ``/portfolio/summary``
                endpoint.  Must contain an ``"equity"`` key with the total
                USDT value as a numeric string or ``Decimal``.
            positions: List of open position dicts as returned by
                ``get_positions()``.  Each dict must contain ``"symbol"``
                and ``"market_value"`` (or ``"value"``) keys.
            recent_pnl: The most recent realised PnL figure for the current
                trading day (negative means a loss).  Used for the daily-loss
                halt check.  Pass ``Decimal("0")`` if unknown.

        Returns:
            A frozen :class:`RiskAssessment` with all metrics and a verdict.

        Example::

            assessment = await agent.assess(
                portfolio={"equity": "9750.00"},
                positions=[{"symbol": "BTCUSDT", "market_value": "1000.00"}],
                recent_pnl=Decimal("-250.00"),
            )
        """
        equity = self._extract_equity(portfolio)

        # Update peak equity — drawdown is relative to the highest level seen.
        if equity > self._peak_equity:
            self._peak_equity = equity
            self._log.debug("peak_equity_updated", peak=str(equity))

        total_position_value, max_single_value = self._compute_position_values(positions)

        # Exposure fractions.
        total_exposure_pct = self._safe_divide(total_position_value, equity)
        max_single_position_pct = self._safe_divide(max_single_value, equity)

        # Drawdown from peak.
        drawdown_pct = self._compute_drawdown(equity)

        # Correlation risk.
        correlation_risk = self._compute_correlation_risk(positions)

        # Daily-loss halt check (absolute loss relative to current equity).
        daily_loss_halt_threshold = self._config.daily_loss_halt * equity
        daily_loss_amount = -recent_pnl  # positive when pnl is negative

        # Determine verdict (HALT takes priority over REDUCE).
        verdict: str
        action: str | None = None

        if daily_loss_amount >= daily_loss_halt_threshold and daily_loss_amount > Decimal("0"):
            verdict = "HALT"
            action = (
                f"Daily loss of {daily_loss_amount.quantize(_D8, ROUND_HALF_UP)} USDT "
                f"exceeds {self._config.daily_loss_halt * 100:.1f}% halt threshold. "
                "Stop all new trades until next session."
            )
            self._log.warning(
                "risk_verdict_halt",
                daily_loss=str(daily_loss_amount),
                threshold=str(daily_loss_halt_threshold),
            )
        elif drawdown_pct >= float(self._config.max_drawdown_trigger):
            verdict = "REDUCE"
            largest_position = self._find_largest_position(positions, equity)
            if largest_position:
                action = f"Reduce or close position in {largest_position} to lower drawdown exposure."
            else:
                action = "Reduce overall position size to recover from drawdown."
            self._log.warning(
                "risk_verdict_reduce",
                drawdown_pct=f"{drawdown_pct:.4f}",
                trigger=str(self._config.max_drawdown_trigger),
            )
        else:
            verdict = "OK"

        # Compute the drawdown-profile scale factor from the current drawdown.
        # When verdict is HALT, force scale_factor to 0.0 so downstream
        # consumers do not accidentally size any position.
        scale_factor: float
        if verdict == "HALT":
            scale_factor = 0.0
        else:
            scale_factor = self._drawdown_profile.scale_factor(drawdown_pct)

        assessment = RiskAssessment(
            total_exposure_pct=float(total_exposure_pct),
            max_single_position_pct=float(max_single_position_pct),
            drawdown_pct=drawdown_pct,
            correlation_risk=correlation_risk,
            verdict=verdict,
            action=action,
            equity=equity.quantize(_D8, ROUND_HALF_UP),
            peak_equity=self._peak_equity.quantize(_D8, ROUND_HALF_UP),
            scale_factor=scale_factor,
        )

        self._log.info(
            "risk_assessed",
            verdict=verdict,
            exposure_pct=f"{total_exposure_pct:.4f}",
            drawdown_pct=f"{drawdown_pct:.4f}",
            correlation_risk=correlation_risk,
            scale_factor=f"{scale_factor:.4f}",
            profile=self._drawdown_profile.name,
        )
        return assessment

    async def check_trade(
        self,
        proposed_signal: dict[str, Any],
        portfolio: dict[str, Any],
    ) -> TradeApproval:
        """Check whether a proposed trade signal should be executed.

        Validates the proposed trade against current portfolio exposure limits.
        May reduce the size to fit within limits, or veto the trade entirely.

        The platform enforces per-order hard limits (e.g. max 25 % position
        size) independently.  This method adds a pre-flight check that prevents
        the strategy from sending orders that would push aggregate portfolio
        exposure above the configured ``max_portfolio_exposure`` threshold,
        even if each individual order would pass the platform's checks.

        Args:
            proposed_signal: A trade signal dict with at minimum:
                * ``"symbol"`` (str): The trading pair, e.g. ``"BTCUSDT"``.
                * ``"size_pct"`` (float | str): Desired allocation as a
                  fraction of equity (e.g. ``0.05`` for 5 %).
                The dict may contain additional fields (e.g. ``"side"``,
                ``"confidence"``); they are ignored.
            portfolio: Portfolio summary dict with an ``"equity"`` key and
                an optional ``"positions_value"`` key representing the total
                market value of all current open positions.

        Returns:
            A frozen :class:`TradeApproval` indicating whether to proceed and
            at what (potentially reduced) size.

        Example::

            approval = await agent.check_trade(
                proposed_signal={"symbol": "ETHUSDT", "size_pct": 0.08},
                portfolio={"equity": "10000.00", "positions_value": "2500.00"},
            )
            if approval.approved:
                qty = Decimal("10000") * Decimal(str(approval.adjusted_size_pct))
        """
        equity = self._extract_equity(portfolio)

        if equity <= Decimal("0"):
            return TradeApproval(
                approved=False,
                adjusted_size_pct=0.0,
                reason="Cannot assess trade: equity is zero or unavailable.",
            )

        proposed_size_pct = self._extract_size_pct(proposed_signal)
        current_exposure = self._extract_current_exposure(portfolio, equity)

        remaining_capacity = self._config.max_portfolio_exposure - current_exposure

        # Hard veto: already at or above max portfolio exposure.
        if remaining_capacity <= Decimal("0"):
            return TradeApproval(
                approved=False,
                adjusted_size_pct=0.0,
                reason=(
                    f"Portfolio exposure {float(current_exposure):.1%} already at or above "
                    f"maximum {float(self._config.max_portfolio_exposure):.1%}. "
                    "No new positions allowed until existing ones are reduced."
                ),
            )

        # Hard veto: proposed size alone exceeds max single position limit.
        if proposed_size_pct > self._config.max_single_position:
            proposed_size_pct = self._config.max_single_position
            self._log.info(
                "trade_size_capped_to_single_position_limit",
                original=str(proposed_size_pct),
                capped=str(self._config.max_single_position),
            )

        # Reduce if proposed trade would push total exposure over the limit.
        if proposed_size_pct > remaining_capacity:
            adjusted = remaining_capacity.quantize(Decimal("0.0001"), ROUND_HALF_UP)
            # If the remaining headroom is too small to be meaningful (< 0.5 %),
            # veto rather than executing a negligibly small order.
            if adjusted < Decimal("0.005"):
                return TradeApproval(
                    approved=False,
                    adjusted_size_pct=0.0,
                    reason=(
                        f"Remaining portfolio capacity {float(adjusted):.2%} is below minimum "
                        "0.5% trade size. Veto to avoid negligible order."
                    ),
                )
            self._log.info(
                "trade_size_reduced",
                proposed=str(proposed_size_pct),
                adjusted=str(adjusted),
                reason="portfolio_exposure_limit",
            )
            return TradeApproval(
                approved=True,
                adjusted_size_pct=float(adjusted),
                reason=(
                    f"Reduced from {float(proposed_size_pct):.1%} to {float(adjusted):.1%} "
                    f"to keep total portfolio exposure within "
                    f"{float(self._config.max_portfolio_exposure):.1%} limit."
                ),
            )

        # Trade fits within all limits.
        return TradeApproval(
            approved=True,
            adjusted_size_pct=float(proposed_size_pct),
            reason=(
                f"Trade approved at {float(proposed_size_pct):.1%} allocation. "
                f"Projected total exposure: "
                f"{float(current_exposure + proposed_size_pct):.1%} / "
                f"{float(self._config.max_portfolio_exposure):.1%} max."
            ),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_equity(self, portfolio: dict[str, Any]) -> Decimal:
        """Extract total equity from a portfolio dict.

        Tries the keys ``"equity"``, ``"total_equity"``, and ``"total_value"``
        in that order.  Falls back to ``Decimal("0")`` with a warning log if
        none are found or the value cannot be converted.

        Args:
            portfolio: Portfolio summary dict from the SDK or REST API.

        Returns:
            Total equity as a ``Decimal``.  Returns ``Decimal("0")`` on error.
        """
        for key in ("equity", "total_equity", "total_value"):
            raw = portfolio.get(key)
            if raw is not None:
                try:
                    return Decimal(str(raw))
                except Exception as exc:  # noqa: BLE001 — broad catch by design for resilience
                    self._log.warning("equity_parse_error", key=key, value=str(raw), error=str(exc))
        self._log.warning("equity_not_found_in_portfolio", keys=list(portfolio.keys()))
        return Decimal("0")

    def _extract_size_pct(self, signal: dict[str, Any]) -> Decimal:
        """Extract the proposed trade size fraction from a signal dict.

        Args:
            signal: Trade signal dict; must contain ``"size_pct"``.

        Returns:
            Size as a ``Decimal`` fraction.  Returns ``Decimal("0.05")``
            (5 % default) if the key is missing or unparseable.
        """
        raw = signal.get("size_pct", signal.get("quantity_pct", 0.05))
        try:
            return Decimal(str(raw))
        except Exception as exc:  # noqa: BLE001 — broad catch by design for resilience
            self._log.warning("size_pct_parse_error", value=str(raw), error=str(exc))
            return Decimal("0.05")

    def _extract_current_exposure(
        self, portfolio: dict[str, Any], equity: Decimal
    ) -> Decimal:
        """Compute the current portfolio exposure fraction.

        If ``"positions_value"`` is available in the portfolio dict, that is
        used directly.  Otherwise falls back to ``Decimal("0")`` (assumes
        no open positions), which is a conservative underestimate that will
        err toward approving trades — the caller should supply accurate data.

        Args:
            portfolio: Portfolio summary dict.
            equity: Pre-computed equity (to avoid re-parsing).

        Returns:
            Current exposure as a ``Decimal`` fraction in [0, ∞).
        """
        for key in ("positions_value", "open_positions_value", "position_value"):
            raw = portfolio.get(key)
            if raw is not None:
                try:
                    positions_value = Decimal(str(raw))
                    return self._safe_divide(positions_value, equity)
                except Exception as exc:  # noqa: BLE001 — broad catch by design for resilience
                    self._log.warning(
                        "positions_value_parse_error", key=key, value=str(raw), error=str(exc)
                    )
        return Decimal("0")

    def _compute_position_values(
        self, positions: list[dict[str, Any]]
    ) -> tuple[Decimal, Decimal]:
        """Sum all position market values and find the largest single position.

        Args:
            positions: List of position dicts.  Each must have a ``"symbol"``
                key and a market value under ``"market_value"``, ``"value"``,
                or ``"usdt_value"``.

        Returns:
            A tuple of (total_position_value, max_single_value) both as
            ``Decimal``.  Both are ``Decimal("0")`` if no positions exist.
        """
        total = Decimal("0")
        max_single = Decimal("0")

        for pos in positions:
            value = self._extract_position_value(pos)
            total += value
            if value > max_single:
                max_single = value

        return total, max_single

    def _extract_position_value(self, position: dict[str, Any]) -> Decimal:
        """Extract the market value of a single position.

        Args:
            position: Position dict with at least one market-value key.

        Returns:
            Market value as a ``Decimal``.  Returns ``Decimal("0")`` if no
            recognised key is found or the value cannot be parsed.
        """
        for key in ("market_value", "value", "usdt_value", "notional", "size"):
            raw = position.get(key)
            if raw is not None:
                try:
                    val = Decimal(str(raw))
                    # Only accept positive values — negative means short position
                    # (not currently modelled, but guard against sign errors).
                    return val if val > Decimal("0") else Decimal("0")
                except Exception as exc:  # noqa: BLE001 — broad catch by design for resilience
                    symbol = position.get("symbol", "unknown")
                    self._log.warning(
                        "position_value_parse_error",
                        symbol=symbol,
                        key=key,
                        value=str(raw),
                        error=str(exc),
                    )
        return Decimal("0")

    def _compute_drawdown(self, equity: Decimal) -> float:
        """Compute the current drawdown from peak equity.

        Args:
            equity: Current portfolio equity.

        Returns:
            Drawdown as a float fraction in [0, ∞).  Returns 0.0 if peak
            equity is zero (no history yet).
        """
        if self._peak_equity <= Decimal("0"):
            return 0.0
        decline = self._peak_equity - equity
        if decline <= Decimal("0"):
            return 0.0
        return float(decline / self._peak_equity)

    def _compute_correlation_risk(self, positions: list[dict[str, Any]]) -> str:
        """Determine qualitative correlation risk from sector concentration.

        Assigns each open position to a sector based on its base-asset prefix
        (resolved via ``_SECTOR_MAP``).  Positions with unrecognised base
        assets are grouped into an ``"other"`` sector.  The maximum count of
        positions in any single sector is used to rate risk.

        Thresholds:
            * < ``max_correlated_positions``: ``"low"``
            * == ``max_correlated_positions``: ``"medium"``
            * >  ``max_correlated_positions``: ``"high"``

        Args:
            positions: List of open position dicts; must contain ``"symbol"``.

        Returns:
            One of ``"low"``, ``"medium"``, or ``"high"``.
        """
        if not positions:
            return "low"

        sector_counts: dict[str, int] = {}
        for pos in positions:
            symbol = str(pos.get("symbol", "")).upper()
            if not _SYMBOL_RE.match(symbol):
                continue
            base = self._extract_base_asset(symbol)
            sector = _SECTOR_MAP.get(base, "other")
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

        if not sector_counts:
            return "low"

        max_in_sector = max(sector_counts.values())
        limit = self._config.max_correlated_positions

        if max_in_sector > limit:
            return "high"
        if max_in_sector == limit:
            return "medium"
        return "low"

    def _find_largest_position(
        self, positions: list[dict[str, Any]], equity: Decimal
    ) -> str | None:
        """Find the symbol of the largest open position by market value.

        Args:
            positions: List of open position dicts.
            equity: Current total equity (unused in ranking but kept for
                future relative-size filtering).

        Returns:
            The symbol string of the largest position, or ``None`` if the
            positions list is empty.
        """
        best_symbol: str | None = None
        best_value = Decimal("0")

        for pos in positions:
            value = self._extract_position_value(pos)
            if value > best_value:
                best_value = value
                best_symbol = str(pos.get("symbol", ""))

        return best_symbol or None

    @staticmethod
    def _extract_base_asset(symbol: str) -> str:
        """Strip the quote asset suffix from a trading pair symbol.

        Args:
            symbol: Upper-case trading pair symbol, e.g. ``"BTCUSDT"``.

        Returns:
            The base asset string, e.g. ``"BTC"``.  If no known suffix
            matches, returns the full symbol (treated as its own base).
        """
        for suffix in _QUOTE_SUFFIXES:
            if symbol.endswith(suffix) and len(symbol) > len(suffix):
                return symbol[: -len(suffix)]
        return symbol

    @staticmethod
    def _safe_divide(numerator: Decimal, denominator: Decimal) -> Decimal:
        """Safely divide two Decimal values, returning zero on division by zero.

        Args:
            numerator: Dividend.
            denominator: Divisor.

        Returns:
            ``numerator / denominator``, or ``Decimal("0")`` when
            ``denominator`` is zero.
        """
        if denominator == Decimal("0"):
            return Decimal("0")
        return numerator / denominator
