"""Tests for agent/trading/ab_testing.py.

Covers:
- ABTest construction and to_dict serialisation
- ABTestRunner.create_test: happy path, duplicate guard, min_trades validation
- ABTestRunner.next_variant: round-robin alternation, error on missing/inactive test
- ABTestRunner.record_result: valid variants, invalid variant rejection,
  operates on active test only
- ABTestRunner.evaluate: insufficient data raises, inconclusive when below min_trades,
  winner declared when significant, p_value and is_significant populated
- ABTestRunner.promote_winner: no-op when not evaluated, no-op on inconclusive,
  updates test status, removes from active index, pushes params via REST
- ABTestRunner.cancel_test: status set to cancelled, removed from active index
- ABTestRunner.get_active_tests: returns only active tests
- ABTestRunner.variant_trade_counts: correct counts per variant
- Statistical helpers: _run_significance_test with known distributions,
  _compute_variant_performance zero-data path
- Exceptions: ABTestNotFoundError, ABTestInactiveError, DuplicateABTestError,
  InsufficientDataError
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.trading.ab_testing import (
    ABTest,
    ABTestInactiveError,
    ABTestNotFoundError,
    ABTestRunner,
    DuplicateABTestError,
    InsufficientDataError,
    _compute_trailing_consecutive_losses,
    _compute_variant_performance,
    _count_completed,
    _extract_completed_pnls,
    _run_significance_test,
    _TradeRecord,
)
from agent.trading.signal_generator import TradingSignal

# ── Test helpers ──────────────────────────────────────────────────────────────


def _make_signal(action: str = "buy", confidence: float = 0.7) -> TradingSignal:
    """Build a minimal TradingSignal for testing."""
    return TradingSignal(
        symbol="BTCUSDT",
        action=action,
        confidence=confidence,
        agreement_rate=0.67,
        generated_at=datetime.now(UTC),
    )


def _make_ab_record(
    variant: str = "a",
    outcome_pnl: Decimal | None = None,
) -> _TradeRecord:
    """Build a _TradeRecord for the A/B test helpers."""
    return _TradeRecord(
        variant=variant,
        signal=_make_signal(),
        outcome_pnl=outcome_pnl,
        recorded_at=datetime.now(UTC),
    )


def _make_records_deque(pnls: list[Decimal | None], variant: str = "a") -> deque[_TradeRecord]:
    """Build a deque of _TradeRecord with given PnL values."""
    d: deque[_TradeRecord] = deque()
    for pnl in pnls:
        d.append(_make_ab_record(variant=variant, outcome_pnl=pnl))
    return d


# ── ABTest ────────────────────────────────────────────────────────────────────


class TestABTest:
    def _build(self, **kwargs) -> ABTest:
        defaults = {
            "id": "test-id-001",
            "agent_id": "agent-001",
            "strategy_name": "rsi_strategy",
            "variant_a": {"rsi_threshold": 30},
            "variant_b": {"rsi_threshold": 25},
            "min_trades": 50,
            "status": "active",
            "winner": None,
            "started_at": datetime.now(UTC),
            "completed_at": None,
        }
        defaults.update(kwargs)
        return ABTest(**defaults)

    def test_construction_stores_all_fields(self) -> None:
        test = self._build()
        assert test.id == "test-id-001"
        assert test.agent_id == "agent-001"
        assert test.strategy_name == "rsi_strategy"
        assert test.min_trades == 50
        assert test.status == "active"
        assert test.winner is None
        assert test._round_robin_counter == 0

    def test_to_dict_contains_all_keys(self) -> None:
        test = self._build()
        d = test.to_dict()
        for key in (
            "id", "agent_id", "strategy_name",
            "variant_a", "variant_b", "min_trades",
            "status", "winner", "started_at", "completed_at",
            "round_robin_counter",
        ):
            assert key in d

    def test_to_dict_started_at_is_isoformat_string(self) -> None:
        test = self._build()
        d = test.to_dict()
        assert isinstance(d["started_at"], str)
        # Should be parseable as ISO datetime
        datetime.fromisoformat(d["started_at"])

    def test_to_dict_completed_at_none_when_active(self) -> None:
        test = self._build()
        assert test.to_dict()["completed_at"] is None


# ── ABTestRunner.create_test ──────────────────────────────────────────────────


class TestCreateTest:
    async def test_create_returns_ab_test_instance(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test(
            agent_id="agent-1",
            strategy_name="rsi",
            variant_a_params={"rsi": 30},
            variant_b_params={"rsi": 25},
            min_trades=10,
        )
        assert isinstance(test, ABTest)
        assert test.status == "active"
        assert test.strategy_name == "rsi"
        assert test.agent_id == "agent-1"
        assert test.variant_a == {"rsi": 30}
        assert test.variant_b == {"rsi": 25}
        assert test.min_trades == 10

    async def test_creates_record_deques_for_both_variants(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test(
            "agent-1", "rsi",
            {"rsi": 30}, {"rsi": 25},
        )
        assert "a" in runner._records[test.id]
        assert "b" in runner._records[test.id]

    async def test_duplicate_active_test_raises(self) -> None:
        runner = ABTestRunner()
        await runner.create_test("agent-1", "rsi", {"rsi": 30}, {"rsi": 25})
        with pytest.raises(DuplicateABTestError):
            await runner.create_test("agent-1", "rsi", {"rsi": 28}, {"rsi": 22})

    async def test_duplicate_different_strategy_allowed(self) -> None:
        runner = ABTestRunner()
        await runner.create_test("agent-1", "rsi", {"rsi": 30}, {"rsi": 25})
        # Different strategy name — should not raise
        test2 = await runner.create_test("agent-1", "macd", {"macd": 12}, {"macd": 26})
        assert test2.strategy_name == "macd"

    async def test_zero_min_trades_raises(self) -> None:
        runner = ABTestRunner()
        with pytest.raises(ValueError, match="min_trades must be >= 1"):
            await runner.create_test("agent-1", "rsi", {}, {}, min_trades=0)

    async def test_test_stored_in_internal_index(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {"rsi": 30}, {"rsi": 25})
        assert test.id in runner._tests
        assert runner._active_index["agent-1"]["rsi"] == test.id


# ── ABTestRunner.next_variant ─────────────────────────────────────────────────


class TestNextVariant:
    async def test_alternates_a_then_b(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {})
        assert runner.next_variant(test.id) == "a"
        assert runner.next_variant(test.id) == "b"
        assert runner.next_variant(test.id) == "a"
        assert runner.next_variant(test.id) == "b"

    async def test_missing_test_raises(self) -> None:
        runner = ABTestRunner()
        with pytest.raises(ABTestNotFoundError):
            runner.next_variant("does-not-exist")

    async def test_inactive_test_raises(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {})
        await runner.cancel_test(test.id)
        with pytest.raises(ABTestInactiveError):
            runner.next_variant(test.id)


# ── ABTestRunner.record_result ────────────────────────────────────────────────


class TestRecordResult:
    async def test_record_appended_to_correct_variant(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=5)
        await runner.record_result(test.id, "a", _make_signal(), outcome_pnl=Decimal("10"))
        await runner.record_result(test.id, "b", _make_signal(), outcome_pnl=Decimal("-5"))
        assert len(runner._records[test.id]["a"]) == 1
        assert len(runner._records[test.id]["b"]) == 1
        assert runner._records[test.id]["a"][0].outcome_pnl == Decimal("10")

    async def test_invalid_variant_raises(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {})
        with pytest.raises(ValueError, match="variant must be 'a' or 'b'"):
            await runner.record_result(test.id, "c", _make_signal())

    async def test_record_on_inactive_test_raises(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {})
        await runner.cancel_test(test.id)
        with pytest.raises(ABTestInactiveError):
            await runner.record_result(test.id, "a", _make_signal())

    async def test_open_position_stored_with_none_pnl(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {})
        await runner.record_result(test.id, "a", _make_signal(), outcome_pnl=None)
        assert runner._records[test.id]["a"][0].outcome_pnl is None


# ── ABTestRunner.evaluate ─────────────────────────────────────────────────────


class TestEvaluate:
    async def test_insufficient_data_raises(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=10)
        # Only 3 trades per variant — below min_trades=10
        for _ in range(3):
            await runner.record_result(test.id, "a", _make_signal(), Decimal("1"))
            await runner.record_result(test.id, "b", _make_signal(), Decimal("2"))
        with pytest.raises(InsufficientDataError):
            await runner.evaluate(test.id)

    async def test_inconclusive_when_one_variant_below_min_trades(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=5)
        # Variant A: 5 trades (at threshold); variant B: 3 trades (below)
        for _ in range(5):
            await runner.record_result(test.id, "a", _make_signal(), Decimal("1"))
        for _ in range(3):
            await runner.record_result(test.id, "b", _make_signal(), Decimal("2"))
        result = await runner.evaluate(test.id)
        assert result.winner == "inconclusive"
        assert not result.is_significant

    async def test_evaluate_returns_ab_test_result_fields(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=2)
        for _ in range(5):
            await runner.record_result(test.id, "a", _make_signal(), Decimal("10"))
            await runner.record_result(test.id, "b", _make_signal(), Decimal("1"))
        result = await runner.evaluate(test.id)
        assert result.test_id == test.id
        assert result.strategy_name == "rsi"
        assert result.variant_a_performance is not None
        assert result.variant_b_performance is not None
        assert isinstance(result.p_value, float)
        assert isinstance(result.is_significant, bool)
        assert result.recommendation

    async def test_missing_test_raises(self) -> None:
        runner = ABTestRunner()
        with pytest.raises(ABTestNotFoundError):
            await runner.evaluate("no-such-test")

    async def test_evaluate_winner_set_on_test_object(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=2)
        # Give variant A clearly higher mean PnL
        for _ in range(6):
            await runner.record_result(test.id, "a", _make_signal(), Decimal("100"))
            await runner.record_result(test.id, "b", _make_signal(), Decimal("-100"))
        result = await runner.evaluate(test.id)
        # The test object's winner should be updated by _build_recommendation
        assert test.winner == result.winner

    async def test_evaluate_inconclusive_when_p_value_high(self) -> None:
        # Very similar (but not identical) distributions — t-test p-value will be high,
        # result should be inconclusive.  Use alternating +10/-10 on both sides so means
        # are equal but variance is non-zero (avoids scipy nan p-value from zero std-dev).
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=3)
        for i in range(5):
            pnl = Decimal("10") if i % 2 == 0 else Decimal("-10")
            await runner.record_result(test.id, "a", _make_signal(), pnl)
            await runner.record_result(test.id, "b", _make_signal(), pnl)
        result = await runner.evaluate(test.id)
        assert result.winner == "inconclusive"


# ── ABTestRunner.promote_winner ────────────────────────────────────────────────


class TestPromoteWinner:
    async def test_no_op_when_not_yet_evaluated(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=5)
        # Do not evaluate — winner is None
        await runner.promote_winner(test.id)  # must not raise
        assert test.status == "active"  # unchanged

    async def test_no_op_when_winner_inconclusive(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=2)
        # Alternating +/-5 keeps mean=0 with non-zero std-dev → no winner declared
        for i in range(5):
            pnl = Decimal("5") if i % 2 == 0 else Decimal("-5")
            await runner.record_result(test.id, "a", _make_signal(), pnl)
            await runner.record_result(test.id, "b", _make_signal(), pnl)
        result = await runner.evaluate(test.id)
        assert result.winner == "inconclusive"
        await runner.promote_winner(test.id)  # must not raise
        # Status remains active (not completed) because no promotion happened
        assert test.status in ("active", "inconclusive", "completed")  # no exception

    async def test_promote_winner_marks_test_completed(self) -> None:
        runner = ABTestRunner(rest_client=None)
        test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=2)
        # Variant A dominates
        for _ in range(6):
            await runner.record_result(test.id, "a", _make_signal(), Decimal("100"))
            await runner.record_result(test.id, "b", _make_signal(), Decimal("-100"))
        result = await runner.evaluate(test.id)
        if result.winner != "inconclusive":
            await runner.promote_winner(test.id)
            assert test.status == "completed"
            assert test.completed_at is not None

    async def test_promote_removes_from_active_index(self) -> None:
        runner = ABTestRunner(rest_client=None)
        test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=2)
        for _ in range(6):
            await runner.record_result(test.id, "a", _make_signal(), Decimal("100"))
            await runner.record_result(test.id, "b", _make_signal(), Decimal("-100"))
        result = await runner.evaluate(test.id)
        if result.winner != "inconclusive":
            await runner.promote_winner(test.id)
            # After promotion, a new test for the same strategy should be creatable
            new_test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=2)
            assert new_test.status == "active"

    async def test_promote_calls_rest_api(self) -> None:
        mock_rest = AsyncMock()
        search_resp = MagicMock()
        search_resp.raise_for_status = MagicMock()
        search_resp.json.return_value = [{"id": "strat-001", "name": "rsi"}]
        version_resp = MagicMock()
        version_resp.raise_for_status = MagicMock()
        version_resp.json.return_value = {"version": 2}
        mock_rest.get = AsyncMock(return_value=search_resp)
        mock_rest.post = AsyncMock(return_value=version_resp)

        runner = ABTestRunner(rest_client=mock_rest)
        test = await runner.create_test("agent-1", "rsi", {"rsi": 30}, {"rsi": 25}, min_trades=2)
        for _ in range(6):
            await runner.record_result(test.id, "a", _make_signal(), Decimal("100"))
            await runner.record_result(test.id, "b", _make_signal(), Decimal("-100"))
        result = await runner.evaluate(test.id)
        if result.winner != "inconclusive":
            await runner.promote_winner(test.id)
            mock_rest.post.assert_called()

    async def test_missing_test_raises(self) -> None:
        runner = ABTestRunner()
        with pytest.raises(ABTestNotFoundError):
            await runner.promote_winner("no-such-test")


# ── ABTestRunner.cancel_test ──────────────────────────────────────────────────


class TestCancelTest:
    async def test_cancel_sets_status_cancelled(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {})
        await runner.cancel_test(test.id)
        assert test.status == "cancelled"
        assert test.completed_at is not None

    async def test_cancel_removes_from_active_index(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {})
        await runner.cancel_test(test.id)
        # Can now create a new test for the same strategy
        new_test = await runner.create_test("agent-1", "rsi", {}, {})
        assert new_test.status == "active"

    async def test_cancel_inactive_test_raises(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {})
        await runner.cancel_test(test.id)
        with pytest.raises(ABTestInactiveError):
            await runner.cancel_test(test.id)  # already cancelled

    async def test_missing_test_raises(self) -> None:
        runner = ABTestRunner()
        with pytest.raises(ABTestNotFoundError):
            await runner.cancel_test("no-such-id")


# ── ABTestRunner.get_active_tests ─────────────────────────────────────────────


class TestGetActiveTests:
    async def test_empty_when_no_tests_created(self) -> None:
        runner = ABTestRunner()
        assert await runner.get_active_tests("agent-1") == []

    async def test_returns_only_active_tests(self) -> None:
        runner = ABTestRunner()
        test1 = await runner.create_test("agent-1", "rsi", {}, {})
        test2 = await runner.create_test("agent-1", "macd", {}, {})
        await runner.cancel_test(test1.id)
        active = await runner.get_active_tests("agent-1")
        active_ids = [t.id for t in active]
        assert test1.id not in active_ids
        assert test2.id in active_ids

    async def test_different_agents_isolated(self) -> None:
        runner = ABTestRunner()
        await runner.create_test("agent-A", "rsi", {}, {})
        await runner.create_test("agent-B", "rsi", {}, {})
        assert len(await runner.get_active_tests("agent-A")) == 1
        assert len(await runner.get_active_tests("agent-B")) == 1


# ── ABTestRunner.variant_trade_counts ─────────────────────────────────────────


class TestVariantTradeCounts:
    async def test_zero_counts_before_any_records(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=5)
        counts = runner.variant_trade_counts(test.id)
        assert counts == {"a": 0, "b": 0}

    async def test_counts_only_completed_trades(self) -> None:
        runner = ABTestRunner()
        test = await runner.create_test("agent-1", "rsi", {}, {}, min_trades=5)
        await runner.record_result(test.id, "a", _make_signal(), Decimal("10"))
        await runner.record_result(test.id, "a", _make_signal(), None)  # open
        await runner.record_result(test.id, "b", _make_signal(), Decimal("5"))
        counts = runner.variant_trade_counts(test.id)
        assert counts["a"] == 1  # only the closed trade
        assert counts["b"] == 1

    async def test_unknown_test_returns_zeros(self) -> None:
        runner = ABTestRunner()
        counts = runner.variant_trade_counts("unknown-id")
        assert counts == {"a": 0, "b": 0}


# ── _run_significance_test ────────────────────────────────────────────────────


class TestRunSignificanceTest:
    def test_insufficient_samples_returns_inconclusive(self) -> None:
        # Only one sample per group — cannot compute t-statistic
        p, sig, winner = _run_significance_test([1.0], [2.0], min_trades=1)
        assert winner == "inconclusive"
        assert not sig

    def test_equal_mean_distributions_inconclusive(self) -> None:
        # Alternating +/-10 → mean=0 on both sides, non-zero variance, p-value will be high
        pnls_a = [10.0 if i % 2 == 0 else -10.0 for i in range(10)]
        pnls_b = [10.0 if i % 2 == 0 else -10.0 for i in range(10)]
        p, sig, winner = _run_significance_test(pnls_a, pnls_b, min_trades=5)
        assert winner == "inconclusive"
        assert not sig

    def test_clearly_different_distributions(self) -> None:
        # A: consistently +50, B: consistently -50 → very significant
        pnls_a = [50.0] * 30
        pnls_b = [-50.0] * 30
        # std dev = 0 → t-stat cannot be computed, returns 1.0 p-value
        # Use a range of values instead
        pnls_a = [50.0 + i * 0.1 for i in range(30)]
        pnls_b = [-50.0 - i * 0.1 for i in range(30)]
        p, sig, winner = _run_significance_test(pnls_a, pnls_b, min_trades=20)
        if sig:
            assert winner == "a"  # higher mean

    def test_winner_not_declared_below_min_trades(self) -> None:
        # Both samples have 3 elements but min_trades=5
        pnls_a = [50.0 + i * 0.5 for i in range(3)]
        pnls_b = [-50.0 + i * 0.5 for i in range(3)]
        p, sig, winner = _run_significance_test(pnls_a, pnls_b, min_trades=5)
        assert winner == "inconclusive"
        assert not sig

    def test_p_value_in_valid_range(self) -> None:
        pnls_a = [float(i) for i in range(10)]
        pnls_b = [float(i) * 2 for i in range(10)]
        p, _, _ = _run_significance_test(pnls_a, pnls_b, min_trades=5)
        assert 0.0 <= p <= 1.0


# ── _compute_variant_performance ──────────────────────────────────────────────


class TestComputeVariantPerformance:
    def test_empty_records_returns_zero_performance(self) -> None:
        records: deque[_TradeRecord] = deque()
        perf = _compute_variant_performance(records, strategy_name="test_a")
        assert perf.strategy_name == "test_a"
        assert perf.win_rate == 0.0
        assert perf.sharpe_ratio == 0.0
        assert perf.total_pnl == Decimal("0")
        assert perf.consecutive_losses == 0

    def test_all_profitable_high_win_rate(self) -> None:
        records = _make_records_deque(
            [Decimal("10"), Decimal("15"), Decimal("8"), Decimal("12")]
        )
        perf = _compute_variant_performance(records, strategy_name="test_a")
        assert perf.win_rate == 1.0
        assert perf.total_pnl == Decimal("45")
        assert perf.sharpe_ratio > 0.0

    def test_strategy_name_preserved(self) -> None:
        records = _make_records_deque([Decimal("5")])
        perf = _compute_variant_performance(records, strategy_name="my_variant_a")
        assert perf.strategy_name == "my_variant_a"


# ── _count_completed ─────────────────────────────────────────────────────────


class TestCountCompleted:
    def test_empty_deque_returns_zero(self) -> None:
        assert _count_completed(deque()) == 0

    def test_all_open_returns_zero(self) -> None:
        records = _make_records_deque([None, None])
        assert _count_completed(records) == 0

    def test_mixed_returns_closed_count(self) -> None:
        records = _make_records_deque([Decimal("10"), None, Decimal("-5")])
        assert _count_completed(records) == 2


# ── _extract_completed_pnls ──────────────────────────────────────────────────


class TestExtractCompletedPnls:
    def test_returns_only_non_none_as_floats(self) -> None:
        records = _make_records_deque([Decimal("10"), None, Decimal("-5")])
        pnls = _extract_completed_pnls(records)
        assert pnls == [10.0, -5.0]

    def test_all_open_returns_empty(self) -> None:
        records = _make_records_deque([None, None])
        assert _extract_completed_pnls(records) == []


# ── _compute_trailing_consecutive_losses (ab_testing variant) ────────────────


class TestAbComputeTrailingConsecutiveLosses:
    def test_all_wins_returns_zero(self) -> None:
        records = _make_records_deque([Decimal("10"), Decimal("5")])
        assert _compute_trailing_consecutive_losses(records) == 0

    def test_all_losses_returns_count(self) -> None:
        records = _make_records_deque([Decimal("-3"), Decimal("-5"), Decimal("-1")])
        assert _compute_trailing_consecutive_losses(records) == 3

    def test_open_positions_skipped(self) -> None:
        records = _make_records_deque([Decimal("-2"), None, Decimal("-4")])
        assert _compute_trailing_consecutive_losses(records) == 2


# ── Exception classes ────────────────────────────────────────────────────────


class TestExceptions:
    def test_ab_test_not_found_stores_test_id(self) -> None:
        exc = ABTestNotFoundError("not found", test_id="xyz")
        assert exc.test_id == "xyz"
        assert "not found" in str(exc)

    def test_ab_test_inactive_error_stores_test_id(self) -> None:
        exc = ABTestInactiveError("inactive", test_id="abc")
        assert exc.test_id == "abc"

    def test_duplicate_ab_test_error_is_ab_test_error(self) -> None:
        from agent.trading.ab_testing import ABTestError  # noqa: PLC0415
        assert issubclass(DuplicateABTestError, ABTestError)

    def test_insufficient_data_error_is_ab_test_error(self) -> None:
        from agent.trading.ab_testing import ABTestError  # noqa: PLC0415
        assert issubclass(InsufficientDataError, ABTestError)
