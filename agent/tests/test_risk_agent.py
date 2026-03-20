"""Tests for agent/strategies/risk/risk_agent.py — RiskAgent, RiskConfig, RiskAssessment."""

from __future__ import annotations

from decimal import Decimal

from agent.strategies.risk.risk_agent import RiskAgent, RiskConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(config: RiskConfig | None = None) -> RiskAgent:
    """Return a fresh RiskAgent with no peak equity history."""
    return RiskAgent(config=config or RiskConfig())


def _portfolio(equity: str, positions_value: str = "0") -> dict:
    """Build a minimal portfolio dict for tests."""
    return {"equity": equity, "positions_value": positions_value}


def _position(symbol: str, market_value: str) -> dict:
    """Build a minimal position dict."""
    return {"symbol": symbol, "market_value": market_value}


# ---------------------------------------------------------------------------
# RiskConfig defaults
# ---------------------------------------------------------------------------


class TestRiskConfigDefaults:
    """Verify that RiskConfig ships with safe conservative defaults."""

    def test_max_portfolio_exposure_default(self) -> None:
        """Default max portfolio exposure is 30 %."""
        cfg = RiskConfig()
        assert cfg.max_portfolio_exposure == Decimal("0.30")

    def test_max_single_position_default(self) -> None:
        """Default max single position is 10 %."""
        cfg = RiskConfig()
        assert cfg.max_single_position == Decimal("0.10")

    def test_max_drawdown_trigger_default(self) -> None:
        """Default drawdown trigger is 5 %."""
        cfg = RiskConfig()
        assert cfg.max_drawdown_trigger == Decimal("0.05")

    def test_daily_loss_halt_default(self) -> None:
        """Default daily-loss halt is 3 %."""
        cfg = RiskConfig()
        assert cfg.daily_loss_halt == Decimal("0.03")

    def test_max_correlated_positions_default(self) -> None:
        """Default correlation limit is 2 positions per sector."""
        cfg = RiskConfig()
        assert cfg.max_correlated_positions == 2

    def test_custom_config_overrides(self) -> None:
        """Keyword overrides replace default thresholds."""
        cfg = RiskConfig(max_drawdown_trigger=Decimal("0.08"), daily_loss_halt=Decimal("0.05"))
        assert cfg.max_drawdown_trigger == Decimal("0.08")
        assert cfg.daily_loss_halt == Decimal("0.05")


# ---------------------------------------------------------------------------
# Exposure calculation
# ---------------------------------------------------------------------------


class TestExposureCalculation:
    """RiskAgent correctly computes total and per-position exposure fractions."""

    async def test_zero_positions_gives_zero_exposure(self) -> None:
        """No open positions → total_exposure_pct and max_single_position_pct are 0.0."""
        agent = _make_agent()
        result = await agent.assess(
            portfolio=_portfolio("10000"),
            positions=[],
            recent_pnl=Decimal("0"),
        )
        assert result.total_exposure_pct == 0.0
        assert result.max_single_position_pct == 0.0

    async def test_single_position_exposure(self) -> None:
        """One 2000 USDT position out of 10 000 equity → 20 % exposure."""
        agent = _make_agent()
        result = await agent.assess(
            portfolio=_portfolio("10000"),
            positions=[_position("BTCUSDT", "2000")],
            recent_pnl=Decimal("0"),
        )
        assert abs(result.total_exposure_pct - 0.2) < 0.0001

    async def test_max_single_position_is_largest(self) -> None:
        """max_single_position_pct reflects the largest individual position."""
        agent = _make_agent()
        positions = [
            _position("BTCUSDT", "3000"),
            _position("ETHUSDT", "1000"),
        ]
        result = await agent.assess(
            portfolio=_portfolio("10000"),
            positions=positions,
            recent_pnl=Decimal("0"),
        )
        # BTCUSDT at 3 000 / 10 000 = 30 %
        assert abs(result.max_single_position_pct - 0.30) < 0.0001
        assert abs(result.total_exposure_pct - 0.40) < 0.0001

    async def test_equity_from_total_equity_key(self) -> None:
        """Portfolio dict with 'total_equity' key is accepted as equity."""
        agent = _make_agent()
        result = await agent.assess(
            portfolio={"total_equity": "5000"},
            positions=[_position("SOLUSDT", "500")],
            recent_pnl=Decimal("0"),
        )
        assert abs(result.total_exposure_pct - 0.10) < 0.0001

    async def test_equity_from_total_value_key(self) -> None:
        """Portfolio dict with 'total_value' key is accepted as equity."""
        agent = _make_agent()
        result = await agent.assess(
            portfolio={"total_value": "8000"},
            positions=[],
            recent_pnl=Decimal("0"),
        )
        assert result.equity == Decimal("8000").quantize(Decimal("0.00000001"))

    async def test_equity_missing_returns_zero(self) -> None:
        """Portfolio with no recognised equity key → equity field is zero."""
        agent = _make_agent()
        result = await agent.assess(
            portfolio={"something_else": "10000"},
            positions=[],
            recent_pnl=Decimal("0"),
        )
        assert result.equity == Decimal("0")


# ---------------------------------------------------------------------------
# Drawdown calculation and REDUCE verdict
# ---------------------------------------------------------------------------


class TestDrawdownAndReduceVerdict:
    """Drawdown is computed correctly and triggers REDUCE at the threshold."""

    async def test_no_drawdown_when_at_peak(self) -> None:
        """First assess call (peak not set) → drawdown is 0.0."""
        agent = _make_agent()
        result = await agent.assess(
            portfolio=_portfolio("10000"),
            positions=[],
            recent_pnl=Decimal("0"),
        )
        assert result.drawdown_pct == 0.0

    async def test_drawdown_computed_correctly(self) -> None:
        """Peak set at 10 000; equity at 9 400 → 6 % drawdown."""
        agent = _make_agent()
        # Establish peak at 10 000
        await agent.assess(_portfolio("10000"), positions=[], recent_pnl=Decimal("0"))
        # Drop to 9 400 → drawdown = 600 / 10 000 = 0.06
        result = await agent.assess(_portfolio("9400"), positions=[], recent_pnl=Decimal("0"))
        assert abs(result.drawdown_pct - 0.06) < 0.0001

    async def test_drawdown_triggers_reduce_at_threshold(self) -> None:
        """6 % drawdown (> 5 % default threshold) → REDUCE verdict."""
        cfg = RiskConfig(max_drawdown_trigger=Decimal("0.05"))
        agent = _make_agent(cfg)
        await agent.assess(_portfolio("10000"), positions=[], recent_pnl=Decimal("0"))
        result = await agent.assess(_portfolio("9400"), positions=[], recent_pnl=Decimal("0"))
        assert result.verdict == "REDUCE"
        assert result.action is not None
        action_lower = result.action.lower()
        assert "drawdown" in action_lower or "reduce" in action_lower or "position" in action_lower

    async def test_drawdown_below_threshold_gives_ok(self) -> None:
        """4 % drawdown (< 5 % threshold) → OK verdict."""
        cfg = RiskConfig(max_drawdown_trigger=Decimal("0.05"))
        agent = _make_agent(cfg)
        await agent.assess(_portfolio("10000"), positions=[], recent_pnl=Decimal("0"))
        result = await agent.assess(_portfolio("9600"), positions=[], recent_pnl=Decimal("0"))
        assert result.verdict == "OK"

    async def test_reduce_action_names_largest_position(self) -> None:
        """REDUCE action message names the largest open position symbol."""
        cfg = RiskConfig(max_drawdown_trigger=Decimal("0.05"))
        agent = _make_agent(cfg)
        await agent.assess(_portfolio("10000"), positions=[], recent_pnl=Decimal("0"))
        positions = [_position("BTCUSDT", "1000"), _position("ETHUSDT", "500")]
        result = await agent.assess(_portfolio("9400"), positions=positions, recent_pnl=Decimal("0"))
        assert result.verdict == "REDUCE"
        assert "BTCUSDT" in (result.action or "")


# ---------------------------------------------------------------------------
# Peak equity tracking
# ---------------------------------------------------------------------------


class TestPeakEquityTracking:
    """Peak equity monotonically increases and never decreases."""

    async def test_peak_is_updated_on_rising_equity(self) -> None:
        """Each call with higher equity updates peak_equity."""
        agent = _make_agent()
        r1 = await agent.assess(_portfolio("10000"), positions=[], recent_pnl=Decimal("0"))
        r2 = await agent.assess(_portfolio("11000"), positions=[], recent_pnl=Decimal("0"))
        assert r1.peak_equity == Decimal("10000")
        assert r2.peak_equity == Decimal("11000")

    async def test_peak_does_not_decrease(self) -> None:
        """After equity falls, peak_equity stays at the previous high."""
        agent = _make_agent()
        await agent.assess(_portfolio("10000"), positions=[], recent_pnl=Decimal("0"))
        result = await agent.assess(_portfolio("8000"), positions=[], recent_pnl=Decimal("0"))
        assert result.peak_equity == Decimal("10000")

    async def test_peak_advances_past_prior_high(self) -> None:
        """Equity recovering above old peak updates the peak."""
        agent = _make_agent()
        await agent.assess(_portfolio("10000"), positions=[], recent_pnl=Decimal("0"))
        await agent.assess(_portfolio("9000"), positions=[], recent_pnl=Decimal("0"))
        result = await agent.assess(_portfolio("11500"), positions=[], recent_pnl=Decimal("0"))
        assert result.peak_equity == Decimal("11500")
        assert result.drawdown_pct == 0.0

    async def test_initial_peak_is_zero_before_first_assess(self) -> None:
        """Agent starts with peak_equity = 0 before any assessment."""
        agent = _make_agent()
        assert agent._peak_equity == Decimal("0")


# ---------------------------------------------------------------------------
# Daily loss halt verdict
# ---------------------------------------------------------------------------


class TestDailyLossHalt:
    """Daily loss ≥ halt threshold triggers HALT verdict (priority over REDUCE)."""

    async def test_halt_triggered_by_daily_loss(self) -> None:
        """Loss of 400 USDT on 10 000 equity = 4 % > 3 % threshold → HALT."""
        cfg = RiskConfig(daily_loss_halt=Decimal("0.03"))
        agent = _make_agent(cfg)
        result = await agent.assess(
            portfolio=_portfolio("10000"),
            positions=[],
            recent_pnl=Decimal("-400"),
        )
        assert result.verdict == "HALT"
        assert result.action is not None
        assert "daily loss" in result.action.lower()

    async def test_halt_not_triggered_below_threshold(self) -> None:
        """Loss of 200 USDT on 10 000 equity = 2 % < 3 % threshold → OK."""
        cfg = RiskConfig(daily_loss_halt=Decimal("0.03"))
        agent = _make_agent(cfg)
        result = await agent.assess(
            portfolio=_portfolio("10000"),
            positions=[],
            recent_pnl=Decimal("-200"),
        )
        assert result.verdict == "OK"

    async def test_halt_takes_priority_over_reduce(self) -> None:
        """When both daily loss AND drawdown thresholds are breached, HALT wins."""
        cfg = RiskConfig(max_drawdown_trigger=Decimal("0.05"), daily_loss_halt=Decimal("0.03"))
        agent = _make_agent(cfg)
        # First call to establish peak at 10 000
        await agent.assess(_portfolio("10000"), positions=[], recent_pnl=Decimal("0"))
        # Now equity dropped to 9 000 (10 % drawdown) AND daily loss is 500 USDT (5 %)
        result = await agent.assess(
            portfolio=_portfolio("9000"),
            positions=[],
            recent_pnl=Decimal("-500"),
        )
        assert result.verdict == "HALT"

    async def test_positive_pnl_never_triggers_halt(self) -> None:
        """Positive recent_pnl does not trigger HALT (profit is not a loss)."""
        agent = _make_agent()
        result = await agent.assess(
            portfolio=_portfolio("10000"),
            positions=[],
            recent_pnl=Decimal("500"),
        )
        assert result.verdict == "OK"

    async def test_zero_pnl_never_triggers_halt(self) -> None:
        """Zero PnL (no trades) never triggers HALT."""
        agent = _make_agent()
        result = await agent.assess(
            portfolio=_portfolio("10000"),
            positions=[],
            recent_pnl=Decimal("0"),
        )
        assert result.verdict == "OK"


# ---------------------------------------------------------------------------
# Clean portfolio → OK verdict
# ---------------------------------------------------------------------------


class TestOkVerdict:
    """A portfolio within all limits receives an OK verdict."""

    async def test_clean_portfolio_verdict_ok(self) -> None:
        """Small exposure, no drawdown, no daily loss → OK verdict with no action."""
        agent = _make_agent()
        result = await agent.assess(
            portfolio=_portfolio("10000"),
            positions=[_position("BTCUSDT", "500")],
            recent_pnl=Decimal("0"),
        )
        assert result.verdict == "OK"
        assert result.action is None

    async def test_ok_verdict_fields_are_populated(self) -> None:
        """OK verdict RiskAssessment carries correct equity and peak_equity."""
        agent = _make_agent()
        result = await agent.assess(
            portfolio=_portfolio("10000"),
            positions=[],
            recent_pnl=Decimal("0"),
        )
        assert result.equity == Decimal("10000").quantize(Decimal("0.00000001"))
        assert result.peak_equity == Decimal("10000").quantize(Decimal("0.00000001"))
        assert result.drawdown_pct == 0.0


# ---------------------------------------------------------------------------
# Correlation risk detection
# ---------------------------------------------------------------------------


class TestCorrelationRisk:
    """Sector concentration detection returns the correct qualitative label."""

    async def test_no_positions_gives_low_correlation(self) -> None:
        """Empty positions list → correlation_risk is 'low'."""
        agent = _make_agent()
        result = await agent.assess(_portfolio("10000"), positions=[], recent_pnl=Decimal("0"))
        assert result.correlation_risk == "low"

    async def test_single_same_sector_position_is_low(self) -> None:
        """One large-cap position → correlation_risk is 'low'."""
        agent = _make_agent()
        result = await agent.assess(
            portfolio=_portfolio("10000"),
            positions=[_position("BTCUSDT", "1000")],
            recent_pnl=Decimal("0"),
        )
        assert result.correlation_risk == "low"

    async def test_two_same_sector_positions_is_medium(self) -> None:
        """BTC + ETH (both large_cap) with default limit 2 → correlation_risk is 'medium'."""
        agent = _make_agent()
        positions = [
            _position("BTCUSDT", "1000"),
            _position("ETHUSDT", "1000"),
        ]
        result = await agent.assess(_portfolio("10000"), positions=positions, recent_pnl=Decimal("0"))
        assert result.correlation_risk == "medium"

    async def test_three_same_sector_positions_is_high(self) -> None:
        """3 l1_platform positions exceed the default limit of 2 → 'high'."""
        agent = _make_agent()
        positions = [
            _position("SOLUSDT", "1000"),
            _position("AVAXUSDT", "1000"),
            _position("NEARUSDT", "1000"),
        ]
        result = await agent.assess(_portfolio("10000"), positions=positions, recent_pnl=Decimal("0"))
        assert result.correlation_risk == "high"

    async def test_mixed_sectors_stays_low(self) -> None:
        """Positions from different sectors → correlation_risk remains 'low'."""
        agent = _make_agent()
        positions = [
            _position("BTCUSDT", "1000"),   # large_cap
            _position("UNIUSDT", "1000"),   # defi
            _position("MATICUSDT", "1000"), # l2_scaling
        ]
        result = await agent.assess(_portfolio("10000"), positions=positions, recent_pnl=Decimal("0"))
        assert result.correlation_risk == "low"

    async def test_custom_correlation_limit(self) -> None:
        """Custom max_correlated_positions=3: 3 same-sector → 'medium', 4 → 'high'."""
        cfg = RiskConfig(max_correlated_positions=3)
        agent = _make_agent(cfg)
        three_l1 = [
            _position("SOLUSDT", "1000"),
            _position("AVAXUSDT", "1000"),
            _position("NEARUSDT", "1000"),
        ]
        result = await agent.assess(_portfolio("10000"), positions=three_l1, recent_pnl=Decimal("0"))
        assert result.correlation_risk == "medium"

        four_l1 = three_l1 + [_position("FTMUSDT", "1000")]
        result2 = await agent.assess(_portfolio("10000"), positions=four_l1, recent_pnl=Decimal("0"))
        assert result2.correlation_risk == "high"


# ---------------------------------------------------------------------------
# check_trade — pre-trade approval
# ---------------------------------------------------------------------------


class TestCheckTrade:
    """RiskAgent.check_trade approves, resizes, or vetoes a proposed trade."""

    async def test_trade_approved_within_limits(self) -> None:
        """5 % proposed size with 0 % current exposure → approved at 5 %."""
        agent = _make_agent()
        result = await agent.check_trade(
            proposed_signal={"symbol": "BTCUSDT", "size_pct": 0.05},
            portfolio=_portfolio("10000", positions_value="0"),
        )
        assert result.approved is True
        assert abs(result.adjusted_size_pct - 0.05) < 0.0001

    async def test_trade_vetoed_when_at_max_exposure(self) -> None:
        """Portfolio already at 30 % exposure → new trade is vetoed."""
        agent = _make_agent()
        result = await agent.check_trade(
            proposed_signal={"symbol": "ETHUSDT", "size_pct": 0.05},
            portfolio={"equity": "10000", "positions_value": "3000"},  # 30 % = max
        )
        assert result.approved is False
        assert result.adjusted_size_pct == 0.0

    async def test_trade_resized_to_remaining_capacity(self) -> None:
        """20 % current exposure + 15 % proposed = 35 % > 30 % → resized to 10 %."""
        agent = _make_agent()
        result = await agent.check_trade(
            proposed_signal={"symbol": "SOLUSDT", "size_pct": 0.15},
            portfolio={"equity": "10000", "positions_value": "2000"},  # 20 % current
        )
        assert result.approved is True
        # Remaining capacity: 30 % - 20 % = 10 %
        assert abs(result.adjusted_size_pct - 0.10) < 0.001

    async def test_zero_equity_rejects_trade(self) -> None:
        """Zero equity portfolio → trade cannot be assessed, vetoed."""
        agent = _make_agent()
        result = await agent.check_trade(
            proposed_signal={"symbol": "BTCUSDT", "size_pct": 0.05},
            portfolio={"equity": "0"},
        )
        assert result.approved is False

    async def test_size_capped_to_max_single_position(self) -> None:
        """Proposed 15 % exceeds 10 % single-position cap → capped to 10 %."""
        agent = _make_agent()
        result = await agent.check_trade(
            proposed_signal={"symbol": "BTCUSDT", "size_pct": 0.15},
            portfolio=_portfolio("10000", positions_value="0"),
        )
        assert result.approved is True
        assert result.adjusted_size_pct <= 0.10
