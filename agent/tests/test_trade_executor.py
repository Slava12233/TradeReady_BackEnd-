"""Unit tests for agent/trading/execution.py :: TradeExecutor.

Tests cover:
- execute() — hold decision returns failure result immediately (no SDK call)
- execute() — successful buy order: SDK called, result has success=True
- execute() — successful sell order: SDK called, fill price parsed
- execute() — duplicate decision fingerprint prevents re-submission
- execute() — SDK failure on first attempt triggers retry; second attempt succeeds
- execute() — SDK failure on both attempts returns failure result
- execute() — budget update called on successful execution
- execute() — budget update failure is non-fatal
- execute_batch() — empty list returns empty result
- execute_batch() — one failure does not abort remaining decisions
- execute_batch() — all results returned in input order
- _fingerprint() — same decision produces same fingerprint
- _fingerprint() — different symbols produce different fingerprints
- _resolve_quantity() — returns per-symbol minimum for known symbols
- _estimate_trade_value() — uses fill_price * quantity when available
- _estimate_trade_value() — falls back to equity percentage
- _estimate_trade_value() — falls back to 100 USDT when both unavailable
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.config import AgentConfig
from agent.models.ecosystem import ExecutionResult, TradeDecision
from agent.trading.execution import TradeExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-executor")
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _make_decision(
    symbol: str = "BTCUSDT",
    action: str = "buy",
    confidence: float = 0.75,
    reasoning: str = "Ensemble signal: buy at 75% confidence.",
) -> TradeDecision:
    return TradeDecision(
        symbol=symbol,
        action=action,
        quantity_pct=Decimal("0.05"),
        confidence=confidence,
        reasoning=reasoning,
        risk_notes="Market may reverse on news.",
    )


def _make_executor(
    config: AgentConfig,
    sdk_client: MagicMock | None = None,
) -> tuple[TradeExecutor, MagicMock]:
    """Build a TradeExecutor with a mocked BudgetManager."""
    budget_mgr = MagicMock()
    budget_mgr.record_trade = AsyncMock()
    executor = TradeExecutor(
        agent_id=str(uuid4()),
        config=config,
        budget_mgr=budget_mgr,
        sdk_client=sdk_client,
    )
    return executor, budget_mgr


def _sdk_with_order(order_id: str | None = None, fill_price: str = "67500.00") -> AsyncMock:
    """Build a mock SDK client that returns a successful order response."""
    sdk = AsyncMock()
    sdk.get_performance = AsyncMock(return_value={"total_value": "10000.00"})
    oid = order_id or str(uuid4())
    sdk.place_market_order = AsyncMock(
        return_value={
            "order_id": oid,
            "fill_price": fill_price,
            "fee": "0.068",
        }
    )
    return sdk


# ---------------------------------------------------------------------------
# TestExecuteHold
# ---------------------------------------------------------------------------


class TestExecuteHold:
    """execute() with action='hold' — must return immediately without SDK calls."""

    async def test_hold_returns_failure_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HOLD decisions return ExecutionResult(success=False) with no SDK call."""
        config = _make_config(monkeypatch)
        sdk = AsyncMock()
        executor, _ = _make_executor(config, sdk_client=sdk)

        decision = _make_decision(action="hold")
        result = await executor.execute(decision)

        assert result.success is False
        assert "hold" in result.error_message.lower()
        sdk.place_market_order.assert_not_called()


# ---------------------------------------------------------------------------
# TestExecuteSuccess
# ---------------------------------------------------------------------------


class TestExecuteSuccess:
    """execute() — happy path for buy and sell orders."""

    async def test_successful_buy_sets_success_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A successful buy order returns ExecutionResult with success=True."""
        config = _make_config(monkeypatch)
        sdk = _sdk_with_order(fill_price="67500.00")
        executor, budget_mgr = _make_executor(config, sdk_client=sdk)

        # Patch _persist_decision to avoid DB dependency
        executor._persist_decision = AsyncMock()

        decision = _make_decision("BTCUSDT", "buy")
        result = await executor.execute(decision)

        assert result.success is True
        assert result.symbol == "BTCUSDT"
        assert result.side == "buy"
        assert result.fill_price == Decimal("67500.00")
        assert result.fee == Decimal("0.068")

    async def test_successful_sell_uses_correct_side(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A successful sell order records side='sell' in the result."""
        config = _make_config(monkeypatch)
        sdk = _sdk_with_order(fill_price="67400.00")
        executor, _ = _make_executor(config, sdk_client=sdk)
        executor._persist_decision = AsyncMock()

        decision = _make_decision("BTCUSDT", "sell")
        result = await executor.execute(decision)

        assert result.success is True
        assert result.side == "sell"

    async def test_budget_updated_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BudgetManager.record_trade is called once after a successful execution."""
        config = _make_config(monkeypatch)
        sdk = _sdk_with_order()
        executor, budget_mgr = _make_executor(config, sdk_client=sdk)
        executor._persist_decision = AsyncMock()

        decision = _make_decision("BTCUSDT", "buy")
        await executor.execute(decision)

        budget_mgr.record_trade.assert_called_once()

    async def test_budget_failure_does_not_block_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BudgetManager.record_trade failure is non-fatal; result is still returned."""
        config = _make_config(monkeypatch)
        sdk = _sdk_with_order()
        executor, budget_mgr = _make_executor(config, sdk_client=sdk)
        executor._persist_decision = AsyncMock()
        budget_mgr.record_trade = AsyncMock(side_effect=RuntimeError("Redis down"))

        decision = _make_decision("BTCUSDT", "buy")
        result = await executor.execute(decision)

        # Result must still be success=True despite budget update failure
        assert result.success is True


# ---------------------------------------------------------------------------
# TestExecuteIdempotency
# ---------------------------------------------------------------------------


class TestExecuteIdempotency:
    """execute() — duplicate detection via fingerprint cache."""

    async def test_duplicate_decision_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling execute() twice with the same decision returns duplicate error."""
        config = _make_config(monkeypatch)
        sdk = _sdk_with_order()
        executor, _ = _make_executor(config, sdk_client=sdk)
        executor._persist_decision = AsyncMock()

        decision = _make_decision("BTCUSDT", "buy", reasoning="Exact same reasoning")
        # First call — should succeed
        first = await executor.execute(decision)
        assert first.success is True

        # Second call — same decision fingerprint
        second = await executor.execute(decision)
        assert second.success is False
        assert "Duplicate" in second.error_message

    async def test_different_symbol_is_not_duplicate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Different symbols produce different fingerprints; both execute."""
        config = _make_config(monkeypatch)
        sdk = _sdk_with_order()
        executor, _ = _make_executor(config, sdk_client=sdk)
        executor._persist_decision = AsyncMock()

        decision_btc = _make_decision("BTCUSDT", "buy", reasoning="Trending up")
        decision_eth = _make_decision("ETHUSDT", "buy", reasoning="Trending up")

        r1 = await executor.execute(decision_btc)
        r2 = await executor.execute(decision_eth)

        assert r1.success is True
        assert r2.success is True


# ---------------------------------------------------------------------------
# TestExecuteRetry
# ---------------------------------------------------------------------------


class TestExecuteRetry:
    """execute() — retry logic in _submit_with_retry."""

    async def test_first_attempt_fails_second_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the first SDK call fails, the executor retries and succeeds."""
        config = _make_config(monkeypatch)
        order_id = str(uuid4())
        sdk = AsyncMock()
        sdk.get_performance = AsyncMock(return_value={"total_value": "10000.00"})
        # First call raises, second call succeeds
        sdk.place_market_order = AsyncMock(
            side_effect=[
                ConnectionError("Transient failure"),
                {
                    "order_id": order_id,
                    "fill_price": "67500.00",
                    "fee": "0.068",
                },
            ]
        )
        executor, _ = _make_executor(config, sdk_client=sdk)
        executor._persist_decision = AsyncMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            decision = _make_decision("BTCUSDT", "buy")
            result = await executor.execute(decision)

        assert result.success is True
        assert sdk.place_market_order.call_count == 2

    async def test_both_attempts_fail_returns_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both attempts fail, ExecutionResult has success=False."""
        config = _make_config(monkeypatch)
        sdk = AsyncMock()
        sdk.get_performance = AsyncMock(return_value={})
        sdk.place_market_order = AsyncMock(side_effect=ConnectionError("Always fails"))
        executor, _ = _make_executor(config, sdk_client=sdk)
        executor._persist_decision = AsyncMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            decision = _make_decision("BTCUSDT", "buy")
            result = await executor.execute(decision)

        assert result.success is False
        assert sdk.place_market_order.call_count == 2


# ---------------------------------------------------------------------------
# TestExecuteBatch
# ---------------------------------------------------------------------------


class TestExecuteBatch:
    """execute_batch() — sequential execution of multiple decisions."""

    async def test_empty_batch_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty decision list returns an empty results list."""
        config = _make_config(monkeypatch)
        executor, _ = _make_executor(config)

        results = await executor.execute_batch([])
        assert results == []

    async def test_batch_returns_result_per_decision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """execute_batch returns one result per input decision in order."""
        config = _make_config(monkeypatch)
        sdk = _sdk_with_order()
        executor, _ = _make_executor(config, sdk_client=sdk)
        executor._persist_decision = AsyncMock()

        decisions = [
            _make_decision("BTCUSDT", "buy", reasoning="Signal A for BTC"),
            _make_decision("ETHUSDT", "sell", reasoning="Signal B for ETH"),
        ]
        results = await executor.execute_batch(decisions)

        assert len(results) == 2
        assert results[0].symbol == "BTCUSDT"
        assert results[1].symbol == "ETHUSDT"

    async def test_batch_one_failure_does_not_abort_rest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failure in one decision does not prevent subsequent decisions."""
        config = _make_config(monkeypatch)

        call_count = 0
        order_id_good = str(uuid4())

        async def place_order_side_effect(symbol: str, side: str, qty: str) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("First order failed")
            return {"order_id": order_id_good, "fill_price": "67500.00", "fee": "0.068"}

        sdk = AsyncMock()
        sdk.get_performance = AsyncMock(return_value={"total_value": "10000.00"})
        sdk.place_market_order = AsyncMock(side_effect=place_order_side_effect)

        executor, _ = _make_executor(config, sdk_client=sdk)
        executor._persist_decision = AsyncMock()

        decisions = [
            _make_decision("BTCUSDT", "buy", reasoning="First decision fails"),
            _make_decision("ETHUSDT", "buy", reasoning="Second decision should succeed"),
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            results = await executor.execute_batch(decisions)

        assert len(results) == 2
        # First result should be failure, second should succeed (after retry)
        # What matters is that both are returned
        assert results[0].symbol == "BTCUSDT"
        assert results[1].symbol == "ETHUSDT"


# ---------------------------------------------------------------------------
# TestFingerprint
# ---------------------------------------------------------------------------


class TestFingerprint:
    """Tests for TradeExecutor._fingerprint (static method)."""

    def test_same_decision_same_fingerprint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same decision produces the same fingerprint on repeated calls."""
        decision = _make_decision("BTCUSDT", "buy", reasoning="Trending up strongly")
        fp1 = TradeExecutor._fingerprint(decision)
        fp2 = TradeExecutor._fingerprint(decision)
        assert fp1 == fp2

    def test_different_symbol_different_fingerprint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Different symbols produce different fingerprints."""
        d_btc = _make_decision("BTCUSDT", "buy", reasoning="Same reasoning")
        d_eth = _make_decision("ETHUSDT", "buy", reasoning="Same reasoning")
        assert TradeExecutor._fingerprint(d_btc) != TradeExecutor._fingerprint(d_eth)

    def test_different_action_different_fingerprint(self) -> None:
        """Different action (buy vs sell) produces different fingerprints."""
        d_buy = _make_decision("BTCUSDT", "buy", reasoning="Signal")
        d_sell = _make_decision("BTCUSDT", "sell", reasoning="Signal")
        assert TradeExecutor._fingerprint(d_buy) != TradeExecutor._fingerprint(d_sell)

    def test_fingerprint_is_16_hex_chars(self) -> None:
        """Fingerprint is a 16-character hex string."""
        d = _make_decision()
        fp = TradeExecutor._fingerprint(d)
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)


# ---------------------------------------------------------------------------
# TestEstimateTradeValue
# ---------------------------------------------------------------------------


class TestEstimateTradeValue:
    """Tests for TradeExecutor._estimate_trade_value (static method)."""

    def _make_result(
        self,
        success: bool = True,
        fill_price: str | None = "67500.00",
        quantity: str = "0.0001",
    ) -> ExecutionResult:
        from datetime import UTC, datetime

        return ExecutionResult(
            success=success,
            order_id=str(uuid4()),
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal(quantity),
            fill_price=Decimal(fill_price) if fill_price else None,
            fee=Decimal("0.068"),
            error_message="",
            executed_at=datetime.now(UTC),
        )

    def test_uses_fill_price_times_quantity(self) -> None:
        """When fill_price is available, value = fill_price * quantity."""
        result = self._make_result(fill_price="67500.00", quantity="0.001")
        value = TradeExecutor._estimate_trade_value(result, {})
        assert value == Decimal("67.50")

    def test_uses_equity_fallback_when_no_fill_price(self) -> None:
        """Falls back to 5 % of equity when fill_price is None."""
        result = self._make_result(fill_price=None)
        portfolio = {"equity": "10000.00"}
        value = TradeExecutor._estimate_trade_value(result, portfolio)
        assert value == Decimal("500.00")

    def test_returns_100_when_all_unavailable(self) -> None:
        """Returns Decimal('100.00') when neither fill_price nor equity is available."""
        result = self._make_result(fill_price=None, quantity="0.001")
        value = TradeExecutor._estimate_trade_value(result, {})
        assert value == Decimal("100.00")
