"""Tests for DrawdownProfile, DrawdownTier, and preset profiles.

Covers:
    - DrawdownTier construction
    - DrawdownProfile construction, validation, and scale_factor() at boundary conditions
    - AGGRESSIVE_PROFILE: exact boundary values at 0 %, 15 %, 25 %, 40 %
    - MODERATE_PROFILE: exact boundary values at 0 %, 10 %, 20 %, 30 %
    - CONSERVATIVE_PROFILE: exact boundary values at 0 %, 5 %, 10 %
    - RiskConfig.drawdown_profile field and default (MODERATE)
    - RiskAgent.assess() returning correct scale_factor for each profile
    - HALT verdict forces scale_factor=0.0 regardless of profile
    - VetoDecision.scale_factor propagated from RiskAssessment
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agent.strategies.risk.risk_agent import (
    AGGRESSIVE_PROFILE,
    CONSERVATIVE_PROFILE,
    MODERATE_PROFILE,
    DrawdownProfile,
    DrawdownTier,
    RiskAgent,
    RiskAssessment,
    RiskConfig,
)
from agent.strategies.risk.veto import TradeSignal, VetoPipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_assessment_agent(
    profile: DrawdownProfile | None = None,
    drawdown_trigger: str = "0.05",
    daily_loss_halt: str = "0.03",
) -> RiskAgent:
    """Return a fresh RiskAgent wired with the given profile."""
    cfg = RiskConfig(
        max_drawdown_trigger=Decimal(drawdown_trigger),
        daily_loss_halt=Decimal(daily_loss_halt),
        drawdown_profile=profile or MODERATE_PROFILE,
    )
    return RiskAgent(config=cfg, drawdown_profile=profile)


def _portfolio(equity: str) -> dict:
    return {"equity": equity, "positions_value": "0"}


def _signal(size_pct: float = 0.05, confidence: float = 0.80) -> TradeSignal:
    return TradeSignal(symbol="BTCUSDT", side="buy", size_pct=size_pct, confidence=confidence)


async def _assess_at_drawdown(agent: RiskAgent, drawdown_pct: float) -> float:
    """Set peak to 10 000, then assess at equity that produces the desired drawdown.

    drawdown_pct = (10000 - equity) / 10000  →  equity = 10000 * (1 - drawdown_pct)
    """
    # Establish peak
    await agent.assess(_portfolio("10000"), positions=[], recent_pnl=Decimal("0"))
    equity_value = 10000.0 * (1.0 - drawdown_pct)
    result = await agent.assess(
        _portfolio(f"{equity_value:.2f}"),
        positions=[],
        recent_pnl=Decimal("0"),
    )
    return result.scale_factor


# ---------------------------------------------------------------------------
# DrawdownTier
# ---------------------------------------------------------------------------


class TestDrawdownTier:
    """DrawdownTier dataclass construction and field access."""

    def test_fields_accessible(self) -> None:
        """threshold and multiplier fields are readable."""
        tier = DrawdownTier(threshold=0.15, multiplier=0.75)
        assert tier.threshold == 0.15
        assert tier.multiplier == 0.75

    def test_tier_is_frozen(self) -> None:
        """DrawdownTier is immutable (frozen dataclass)."""
        tier = DrawdownTier(threshold=0.10, multiplier=0.50)
        with pytest.raises((AttributeError, TypeError)):
            tier.threshold = 0.20  # type: ignore[misc]

    def test_zero_threshold_allowed(self) -> None:
        """threshold=0.0 is valid (base tier)."""
        tier = DrawdownTier(threshold=0.0, multiplier=1.0)
        assert tier.threshold == 0.0
        assert tier.multiplier == 1.0


# ---------------------------------------------------------------------------
# DrawdownProfile — construction and validation
# ---------------------------------------------------------------------------


class TestDrawdownProfileConstruction:
    """DrawdownProfile validates its tiers on construction."""

    def test_valid_profile_constructs(self) -> None:
        """A profile with a base tier at 0.0 constructs without error."""
        profile = DrawdownProfile(
            name="test",
            tiers=(
                DrawdownTier(threshold=0.0, multiplier=1.0),
                DrawdownTier(threshold=0.10, multiplier=0.5),
            ),
        )
        assert profile.name == "test"
        assert len(profile.tiers) == 2

    def test_tiers_sorted_ascending_on_construction(self) -> None:
        """Tiers provided out of order are sorted by threshold ascending."""
        profile = DrawdownProfile(
            name="unsorted",
            tiers=(
                DrawdownTier(threshold=0.20, multiplier=0.5),
                DrawdownTier(threshold=0.00, multiplier=1.0),
                DrawdownTier(threshold=0.10, multiplier=0.75),
            ),
        )
        thresholds = [t.threshold for t in profile.tiers]
        assert thresholds == sorted(thresholds)

    def test_no_tiers_raises_value_error(self) -> None:
        """Providing an empty tiers tuple raises ValueError."""
        with pytest.raises(ValueError, match="at least one tier"):
            DrawdownProfile(name="empty", tiers=())

    def test_missing_base_tier_raises_value_error(self) -> None:
        """No tier with threshold=0.0 raises ValueError."""
        with pytest.raises(ValueError, match="threshold=0.0"):
            DrawdownProfile(
                name="no_base",
                tiers=(DrawdownTier(threshold=0.10, multiplier=0.75),),
            )

    def test_profile_is_frozen(self) -> None:
        """DrawdownProfile is immutable (frozen dataclass)."""
        profile = DrawdownProfile(
            name="frozen_test",
            tiers=(DrawdownTier(threshold=0.0, multiplier=1.0),),
        )
        with pytest.raises((AttributeError, TypeError)):
            profile.name = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DrawdownProfile.scale_factor() — boundary conditions
# ---------------------------------------------------------------------------


class TestDrawdownProfileScaleFactor:
    """scale_factor() returns correct multiplier at all boundary conditions."""

    def test_below_first_threshold_returns_full(self) -> None:
        """Drawdown of 0.0 returns the base multiplier (1.0)."""
        profile = DrawdownProfile(
            name="test",
            tiers=(
                DrawdownTier(threshold=0.00, multiplier=1.0),
                DrawdownTier(threshold=0.10, multiplier=0.5),
            ),
        )
        assert profile.scale_factor(0.0) == 1.0

    def test_exact_threshold_activates_tier(self) -> None:
        """Drawdown exactly at a threshold returns that tier's multiplier."""
        profile = DrawdownProfile(
            name="test",
            tiers=(
                DrawdownTier(threshold=0.00, multiplier=1.0),
                DrawdownTier(threshold=0.10, multiplier=0.5),
            ),
        )
        # Exactly at 10 % → 0.5×
        assert profile.scale_factor(0.10) == 0.5

    def test_just_below_threshold_stays_in_lower_tier(self) -> None:
        """Drawdown of 9.99 % (< 10 %) stays in the 1.0× base tier."""
        profile = DrawdownProfile(
            name="test",
            tiers=(
                DrawdownTier(threshold=0.00, multiplier=1.0),
                DrawdownTier(threshold=0.10, multiplier=0.5),
            ),
        )
        assert profile.scale_factor(0.0999) == 1.0

    def test_above_highest_threshold_returns_lowest_multiplier(self) -> None:
        """Drawdown above all tiers returns the most restrictive multiplier."""
        profile = DrawdownProfile(
            name="test",
            tiers=(
                DrawdownTier(threshold=0.00, multiplier=1.0),
                DrawdownTier(threshold=0.10, multiplier=0.5),
                DrawdownTier(threshold=0.20, multiplier=0.25),
            ),
        )
        # 50 % drawdown → still 0.25 (the last tier)
        assert profile.scale_factor(0.50) == 0.25

    def test_single_base_tier_always_returns_its_multiplier(self) -> None:
        """A profile with only a base tier always returns that multiplier."""
        profile = DrawdownProfile(
            name="constant",
            tiers=(DrawdownTier(threshold=0.0, multiplier=0.5),),
        )
        for dd in [0.0, 0.10, 0.50, 1.0]:
            assert profile.scale_factor(dd) == 0.5


# ---------------------------------------------------------------------------
# AGGRESSIVE_PROFILE boundary conditions
# ---------------------------------------------------------------------------


class TestAggressiveProfile:
    """AGGRESSIVE_PROFILE: 0–15 % full, 15–25 % 0.75×, 25–40 % 0.5×, >40 % 0.25×."""

    def test_name(self) -> None:
        assert AGGRESSIVE_PROFILE.name == "AGGRESSIVE"

    def test_below_15_percent_full_size(self) -> None:
        """0 % → 1.0×."""
        assert AGGRESSIVE_PROFILE.scale_factor(0.0) == 1.0

    def test_just_below_15_percent_still_full(self) -> None:
        """14.99 % → 1.0× (still below 15 % boundary)."""
        assert AGGRESSIVE_PROFILE.scale_factor(0.1499) == 1.0

    def test_exactly_15_percent_triggers_075(self) -> None:
        """15 % exactly → 0.75×."""
        assert AGGRESSIVE_PROFILE.scale_factor(0.15) == 0.75

    def test_between_15_and_25_is_075(self) -> None:
        """20 % → 0.75×."""
        assert AGGRESSIVE_PROFILE.scale_factor(0.20) == 0.75

    def test_just_below_25_percent_is_075(self) -> None:
        """24.99 % → 0.75×."""
        assert AGGRESSIVE_PROFILE.scale_factor(0.2499) == 0.75

    def test_exactly_25_percent_triggers_05(self) -> None:
        """25 % exactly → 0.5×."""
        assert AGGRESSIVE_PROFILE.scale_factor(0.25) == 0.5

    def test_between_25_and_40_is_05(self) -> None:
        """35 % → 0.5×."""
        assert AGGRESSIVE_PROFILE.scale_factor(0.35) == 0.5

    def test_just_below_40_percent_is_05(self) -> None:
        """39.99 % → 0.5×."""
        assert AGGRESSIVE_PROFILE.scale_factor(0.3999) == 0.5

    def test_exactly_40_percent_triggers_025(self) -> None:
        """40 % exactly → 0.25×."""
        assert AGGRESSIVE_PROFILE.scale_factor(0.40) == 0.25

    def test_above_40_percent_is_025(self) -> None:
        """80 % drawdown → 0.25×."""
        assert AGGRESSIVE_PROFILE.scale_factor(0.80) == 0.25


# ---------------------------------------------------------------------------
# MODERATE_PROFILE boundary conditions
# ---------------------------------------------------------------------------


class TestModerateProfile:
    """MODERATE_PROFILE: 0–10 % full, 10–20 % 0.75×, 20–30 % 0.5×, >30 % 0.25×."""

    def test_name(self) -> None:
        assert MODERATE_PROFILE.name == "MODERATE"

    def test_below_10_percent_full_size(self) -> None:
        """0 % → 1.0×."""
        assert MODERATE_PROFILE.scale_factor(0.0) == 1.0

    def test_just_below_10_percent_still_full(self) -> None:
        """9.99 % → 1.0×."""
        assert MODERATE_PROFILE.scale_factor(0.0999) == 1.0

    def test_exactly_10_percent_triggers_075(self) -> None:
        """10 % exactly → 0.75×."""
        assert MODERATE_PROFILE.scale_factor(0.10) == 0.75

    def test_between_10_and_20_is_075(self) -> None:
        """15 % → 0.75×."""
        assert MODERATE_PROFILE.scale_factor(0.15) == 0.75

    def test_just_below_20_percent_is_075(self) -> None:
        """19.99 % → 0.75×."""
        assert MODERATE_PROFILE.scale_factor(0.1999) == 0.75

    def test_exactly_20_percent_triggers_05(self) -> None:
        """20 % exactly → 0.5×."""
        assert MODERATE_PROFILE.scale_factor(0.20) == 0.5

    def test_between_20_and_30_is_05(self) -> None:
        """25 % → 0.5×."""
        assert MODERATE_PROFILE.scale_factor(0.25) == 0.5

    def test_just_below_30_percent_is_05(self) -> None:
        """29.99 % → 0.5×."""
        assert MODERATE_PROFILE.scale_factor(0.2999) == 0.5

    def test_exactly_30_percent_triggers_025(self) -> None:
        """30 % exactly → 0.25×."""
        assert MODERATE_PROFILE.scale_factor(0.30) == 0.25

    def test_above_30_percent_is_025(self) -> None:
        """70 % drawdown → 0.25×."""
        assert MODERATE_PROFILE.scale_factor(0.70) == 0.25


# ---------------------------------------------------------------------------
# CONSERVATIVE_PROFILE boundary conditions
# ---------------------------------------------------------------------------


class TestConservativeProfile:
    """CONSERVATIVE_PROFILE: 0–5 % full, 5–10 % 0.5×, >10 % 0.25×."""

    def test_name(self) -> None:
        assert CONSERVATIVE_PROFILE.name == "CONSERVATIVE"

    def test_below_5_percent_full_size(self) -> None:
        """0 % → 1.0×."""
        assert CONSERVATIVE_PROFILE.scale_factor(0.0) == 1.0

    def test_just_below_5_percent_still_full(self) -> None:
        """4.99 % → 1.0×."""
        assert CONSERVATIVE_PROFILE.scale_factor(0.0499) == 1.0

    def test_exactly_5_percent_triggers_05(self) -> None:
        """5 % exactly → 0.5×."""
        assert CONSERVATIVE_PROFILE.scale_factor(0.05) == 0.5

    def test_between_5_and_10_is_05(self) -> None:
        """7.5 % → 0.5×."""
        assert CONSERVATIVE_PROFILE.scale_factor(0.075) == 0.5

    def test_just_below_10_percent_is_05(self) -> None:
        """9.99 % → 0.5×."""
        assert CONSERVATIVE_PROFILE.scale_factor(0.0999) == 0.5

    def test_exactly_10_percent_triggers_025(self) -> None:
        """10 % exactly → 0.25×."""
        assert CONSERVATIVE_PROFILE.scale_factor(0.10) == 0.25

    def test_above_10_percent_is_025(self) -> None:
        """50 % drawdown → 0.25×."""
        assert CONSERVATIVE_PROFILE.scale_factor(0.50) == 0.25


# ---------------------------------------------------------------------------
# RiskConfig — drawdown_profile field
# ---------------------------------------------------------------------------


class TestRiskConfigDrawdownProfile:
    """RiskConfig.drawdown_profile field defaults and assignment."""

    def test_default_profile_is_moderate(self) -> None:
        """Default RiskConfig uses MODERATE_PROFILE."""
        cfg = RiskConfig()
        assert cfg.drawdown_profile is MODERATE_PROFILE

    def test_custom_profile_assigned_aggressive(self) -> None:
        """Passing AGGRESSIVE_PROFILE via constructor stores it correctly."""
        cfg = RiskConfig(drawdown_profile=AGGRESSIVE_PROFILE)
        assert cfg.drawdown_profile is AGGRESSIVE_PROFILE
        assert cfg.drawdown_profile.name == "AGGRESSIVE"

    def test_custom_profile_assigned_conservative(self) -> None:
        """Passing CONSERVATIVE_PROFILE via constructor stores it correctly."""
        cfg = RiskConfig(drawdown_profile=CONSERVATIVE_PROFILE)
        assert cfg.drawdown_profile is CONSERVATIVE_PROFILE

    def test_custom_drawdown_profile_instance(self) -> None:
        """Custom DrawdownProfile instance is accepted."""
        custom = DrawdownProfile(
            name="custom",
            tiers=(
                DrawdownTier(threshold=0.00, multiplier=1.0),
                DrawdownTier(threshold=0.08, multiplier=0.6),
            ),
        )
        cfg = RiskConfig(drawdown_profile=custom)
        assert cfg.drawdown_profile.name == "custom"
        assert cfg.drawdown_profile.scale_factor(0.08) == 0.6


# ---------------------------------------------------------------------------
# RiskAgent — scale_factor in RiskAssessment
# ---------------------------------------------------------------------------


class TestRiskAgentScaleFactor:
    """RiskAgent.assess() returns correct scale_factor from the DrawdownProfile."""

    async def test_no_drawdown_returns_full_scale_factor(self) -> None:
        """0 % drawdown → scale_factor=1.0 for all profiles."""
        for profile in [AGGRESSIVE_PROFILE, MODERATE_PROFILE, CONSERVATIVE_PROFILE]:
            agent = _make_assessment_agent(profile=profile)
            result = await agent.assess(_portfolio("10000"), positions=[], recent_pnl=Decimal("0"))
            assert result.scale_factor == 1.0, f"Profile {profile.name} failed at 0% drawdown"

    async def test_aggressive_scale_factor_at_20_percent_drawdown(self) -> None:
        """Aggressive profile: 20 % drawdown → scale_factor=0.75."""
        agent = _make_assessment_agent(profile=AGGRESSIVE_PROFILE, drawdown_trigger="0.50")
        factor = await _assess_at_drawdown(agent, 0.20)
        assert factor == 0.75

    async def test_aggressive_scale_factor_at_30_percent_drawdown(self) -> None:
        """Aggressive profile: 30 % drawdown → scale_factor=0.5."""
        agent = _make_assessment_agent(profile=AGGRESSIVE_PROFILE, drawdown_trigger="0.50")
        factor = await _assess_at_drawdown(agent, 0.30)
        assert factor == 0.5

    async def test_aggressive_scale_factor_at_45_percent_drawdown(self) -> None:
        """Aggressive profile: 45 % drawdown (>40 %) → scale_factor=0.25."""
        agent = _make_assessment_agent(profile=AGGRESSIVE_PROFILE, drawdown_trigger="0.50")
        factor = await _assess_at_drawdown(agent, 0.45)
        assert factor == 0.25

    async def test_moderate_scale_factor_at_15_percent_drawdown(self) -> None:
        """Moderate profile: 15 % drawdown → scale_factor=0.75."""
        agent = _make_assessment_agent(profile=MODERATE_PROFILE, drawdown_trigger="0.50")
        factor = await _assess_at_drawdown(agent, 0.15)
        assert factor == 0.75

    async def test_moderate_scale_factor_at_25_percent_drawdown(self) -> None:
        """Moderate profile: 25 % drawdown → scale_factor=0.5."""
        agent = _make_assessment_agent(profile=MODERATE_PROFILE, drawdown_trigger="0.50")
        factor = await _assess_at_drawdown(agent, 0.25)
        assert factor == 0.5

    async def test_moderate_scale_factor_at_35_percent_drawdown(self) -> None:
        """Moderate profile: 35 % drawdown (>30 %) → scale_factor=0.25."""
        agent = _make_assessment_agent(profile=MODERATE_PROFILE, drawdown_trigger="0.50")
        factor = await _assess_at_drawdown(agent, 0.35)
        assert factor == 0.25

    async def test_conservative_scale_factor_at_7_percent_drawdown(self) -> None:
        """Conservative profile: 7 % drawdown → scale_factor=0.5."""
        agent = _make_assessment_agent(profile=CONSERVATIVE_PROFILE, drawdown_trigger="0.50")
        factor = await _assess_at_drawdown(agent, 0.07)
        assert factor == 0.5

    async def test_conservative_scale_factor_at_15_percent_drawdown(self) -> None:
        """Conservative profile: 15 % drawdown → scale_factor=0.25."""
        agent = _make_assessment_agent(profile=CONSERVATIVE_PROFILE, drawdown_trigger="0.50")
        factor = await _assess_at_drawdown(agent, 0.15)
        assert factor == 0.25

    async def test_halt_verdict_forces_scale_factor_zero(self) -> None:
        """HALT verdict sets scale_factor=0.0 regardless of profile and drawdown."""
        for profile in [AGGRESSIVE_PROFILE, MODERATE_PROFILE, CONSERVATIVE_PROFILE]:
            # daily_loss_halt=0.01 → any 2 % loss triggers HALT
            agent = _make_assessment_agent(
                profile=profile,
                drawdown_trigger="0.50",
                daily_loss_halt="0.01",
            )
            result = await agent.assess(
                _portfolio("10000"),
                positions=[],
                recent_pnl=Decimal("-500"),  # 5 % loss → HALT
            )
            assert result.verdict == "HALT"
            assert result.scale_factor == 0.0, (
                f"Profile {profile.name} did not force scale_factor=0.0 on HALT"
            )

    async def test_scale_factor_field_present_on_ok_verdict(self) -> None:
        """OK verdict RiskAssessment includes scale_factor=1.0 when no drawdown."""
        agent = _make_assessment_agent()
        result = await agent.assess(_portfolio("10000"), positions=[], recent_pnl=Decimal("0"))
        assert result.verdict == "OK"
        assert result.scale_factor == 1.0

    async def test_drawdown_profile_from_config_used_when_no_explicit_arg(self) -> None:
        """RiskAgent uses config.drawdown_profile when no explicit profile arg is passed."""
        cfg = RiskConfig(drawdown_profile=CONSERVATIVE_PROFILE)
        agent = RiskAgent(config=cfg)  # no explicit drawdown_profile arg
        # Conservative profile: 7 % drawdown → 0.5×
        factor = await _assess_at_drawdown(agent, 0.07)
        assert factor == 0.5

    async def test_explicit_profile_overrides_config_profile(self) -> None:
        """Explicit drawdown_profile arg takes precedence over config.drawdown_profile."""
        cfg = RiskConfig(drawdown_profile=CONSERVATIVE_PROFILE)
        # Override with AGGRESSIVE which has 1.0× at 7 %
        agent = RiskAgent(config=cfg, drawdown_profile=AGGRESSIVE_PROFILE)
        factor = await _assess_at_drawdown(agent, 0.07)
        assert factor == 1.0  # aggressive: 7 % is below 15 % threshold

    async def test_different_agents_can_have_different_profiles(self) -> None:
        """Two agents with different profiles produce different scale factors at the same drawdown."""
        aggressive_agent = _make_assessment_agent(
            profile=AGGRESSIVE_PROFILE, drawdown_trigger="0.50"
        )
        conservative_agent = _make_assessment_agent(
            profile=CONSERVATIVE_PROFILE, drawdown_trigger="0.50"
        )
        # At 12 % drawdown: aggressive → 1.0×, conservative → 0.25×
        agg_factor = await _assess_at_drawdown(aggressive_agent, 0.12)
        con_factor = await _assess_at_drawdown(conservative_agent, 0.12)
        assert agg_factor == 1.0
        assert con_factor == 0.25


# ---------------------------------------------------------------------------
# VetoDecision — scale_factor propagation from RiskAssessment
# ---------------------------------------------------------------------------


class TestVetoDecisionScaleFactor:
    """VetoPipeline.evaluate() propagates scale_factor from the RiskAssessment."""

    def _make_assessment(
        self,
        verdict: str = "OK",
        drawdown_pct: float = 0.0,
        scale_factor: float = 1.0,
    ) -> RiskAssessment:
        return RiskAssessment(
            verdict=verdict,
            drawdown_pct=drawdown_pct,
            total_exposure_pct=0.0,
            max_single_position_pct=0.0,
            correlation_risk="low",
            equity=Decimal("10000"),
            peak_equity=Decimal("10000"),
            scale_factor=scale_factor,
        )

    def test_approved_decision_carries_scale_factor(self) -> None:
        """APPROVED VetoDecision includes scale_factor from assessment."""
        pipeline = VetoPipeline()
        signal = _signal()
        assessment = self._make_assessment(scale_factor=0.75)
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "APPROVED"
        assert decision.scale_factor == 0.75

    def test_vetoed_decision_carries_scale_factor(self) -> None:
        """VETOED VetoDecision (HALT verdict) carries scale_factor=0.0."""
        pipeline = VetoPipeline()
        signal = _signal()
        assessment = self._make_assessment(verdict="HALT", scale_factor=0.0)
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "VETOED"
        assert decision.scale_factor == 0.0

    def test_resized_decision_carries_scale_factor(self) -> None:
        """RESIZED VetoDecision carries the scale_factor from the assessment."""
        pipeline = VetoPipeline()
        # Signal drawdown > 3 % threshold triggers a resize in check 5
        assessment = self._make_assessment(drawdown_pct=0.05, scale_factor=0.5)
        signal = _signal(size_pct=0.08, confidence=0.80)
        decision = pipeline.evaluate(signal, assessment)
        # Check 5 fires: drawdown > 3 % → RESIZED; scale_factor is propagated
        assert decision.action == "RESIZED"
        assert decision.scale_factor == 0.5

    def test_low_confidence_veto_propagates_scale_factor(self) -> None:
        """Check-2 veto (low confidence) also carries scale_factor."""
        pipeline = VetoPipeline()
        signal = TradeSignal(symbol="BTCUSDT", side="buy", size_pct=0.05, confidence=0.3)
        assessment = self._make_assessment(scale_factor=0.75)
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "VETOED"
        assert decision.scale_factor == 0.75

    def test_full_scale_factor_when_no_drawdown(self) -> None:
        """scale_factor=1.0 in an OK assessment propagates as 1.0."""
        pipeline = VetoPipeline()
        signal = _signal()
        assessment = self._make_assessment(scale_factor=1.0)
        decision = pipeline.evaluate(signal, assessment)
        assert decision.scale_factor == 1.0

    def test_scale_factor_default_on_veto_decision(self) -> None:
        """VetoDecision.scale_factor defaults to 1.0 when not explicitly set."""
        from agent.strategies.risk.veto import VetoDecision
        decision = VetoDecision(
            action="APPROVED",
            original_size_pct=0.05,
            adjusted_size_pct=0.05,
            reason="test",
        )
        assert decision.scale_factor == 1.0
