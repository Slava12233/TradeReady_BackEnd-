"""Trade execution wrapper for the agent trading loop.

:class:`TradeExecutor` is the single point through which the trading loop
submits orders to the platform.  It enforces idempotency (no duplicate
orders for the same decision), logs pre- and post-trade portfolio state,
retries once on transient SDK failures, records every execution to
``agent_decisions`` with the platform ``order_id``, and updates the
agent's budget counters.

Architecture::

    TradeExecutor.execute(decision)
           │
           ├── 1. Check idempotency cache (abort if already submitted)
           ├── 2. Log pre-trade portfolio state
           ├── 3. Submit order via SDK (retry once on failure)
           ├── 4. Log post-trade portfolio state
           ├── 5. Persist AgentDecision row with order_id
           ├── 6. Update budget counters (BudgetManager.record_trade)
           └── 7. Return ExecutionResult

Usage::

    from agent.config import AgentConfig
    from agent.permissions.budget import BudgetManager
    from agent.trading.execution import TradeExecutor

    executor = TradeExecutor(
        agent_id="uuid",
        config=config,
        budget_mgr=budget_mgr,
        sdk_client=sdk,
    )
    result = await executor.execute(decision)

Idempotency notes
-----------------
:class:`TradeExecutor` maintains an in-memory set of ``(symbol, action,
decision_reasoning_hash)`` tuples that have already been submitted in the
current process lifetime.  If :meth:`execute` is called twice with the same
:class:`~agent.models.ecosystem.TradeDecision` (same symbol + action +
reasoning hash), the second call returns an error result without placing a
second order.  The cache is per-instance and does not survive process
restarts — which is acceptable because the trading loop creates a fresh
executor per session.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from agent.config import AgentConfig
from agent.models.ecosystem import ExecutionResult, TradeDecision
from agent.permissions.budget import BudgetManager

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum quantity string used as a fallback when the decision's quantity_pct
# cannot be resolved against portfolio state.
_FALLBACK_QTY: str = "0.001"

# Per-symbol minimum order quantities for the most common pairs.
_MIN_ORDER_QTY: dict[str, str] = {
    "BTCUSDT": "0.0001",
    "ETHUSDT": "0.001",
    "SOLUSDT": "0.01",
}

# Seconds to wait between the initial SDK failure and the single retry.
_RETRY_DELAY_SECONDS: float = 1.0


# ---------------------------------------------------------------------------
# TradeExecutor
# ---------------------------------------------------------------------------


class TradeExecutor:
    """Executes :class:`~agent.models.ecosystem.TradeDecision` objects via the SDK.

    Wraps SDK ``place_market_order`` with pre/post-state logging, idempotency
    protection, DB persistence of every execution, and budget counter updates.

    Args:
        agent_id: UUID string of the trading agent.
        config: :class:`~agent.config.AgentConfig` with connectivity settings.
        budget_mgr: :class:`~agent.permissions.budget.BudgetManager` instance
            used to record each executed trade against the daily budget.
        sdk_client: An ``AsyncAgentExchangeClient`` (or compatible duck-typed
            object) used to fetch portfolio state and place orders.  When
            ``None`` the executor operates in dry-run mode — all orders are
            simulated with ``success=False`` and no SDK calls are made.

    Example::

        executor = TradeExecutor(
            agent_id="550e8400-...",
            config=config,
            budget_mgr=BudgetManager(config=config),
            sdk_client=sdk,
        )
        result = await executor.execute(decision)
        if result.success:
            print(f"Order {result.order_id} filled at {result.fill_price}")
    """

    def __init__(
        self,
        agent_id: str,
        config: AgentConfig,
        budget_mgr: BudgetManager,
        sdk_client: Any = None,  # noqa: ANN401
    ) -> None:
        self._agent_id = agent_id
        self._config = config
        self._budget_mgr = budget_mgr
        self._sdk_client: Any = sdk_client

        # Idempotency cache: stores decision fingerprints for the current session.
        # Prevents duplicate orders if execute() is called twice with the same decision.
        self._submitted_fingerprints: set[str] = set()

        self._log = logger.bind(agent_id=agent_id, component="trade_executor")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, decision: TradeDecision) -> ExecutionResult:
        """Execute a single :class:`~agent.models.ecosystem.TradeDecision`.

        Pipeline:

        1. **Idempotency check** — abort if this decision was already submitted.
        2. **Pre-trade log** — fetch and log current portfolio state.
        3. **Submit order** — call SDK ``place_market_order``.  On failure,
           wait :data:`_RETRY_DELAY_SECONDS` and retry once before aborting.
        4. **Post-trade log** — fetch and log updated portfolio state.
        5. **Persist** — write an ``AgentDecision`` row with the ``order_id``.
        6. **Budget update** — call :meth:`~BudgetManager.record_trade`.
        7. **Return** :class:`~agent.models.ecosystem.ExecutionResult`.

        Args:
            decision: The :class:`~agent.models.ecosystem.TradeDecision` to
                execute.  Must have ``action`` of ``"buy"`` or ``"sell"``
                (``"hold"`` decisions are returned as an instant no-op with
                ``success=False``).

        Returns:
            An :class:`~agent.models.ecosystem.ExecutionResult` capturing
            the full outcome (success, order_id, fill price, fee, errors).
        """
        if decision.action == "hold":
            return ExecutionResult(
                success=False,
                order_id="",
                symbol=decision.symbol,
                side="buy",  # placeholder — HOLD never reaches platform
                quantity=Decimal("0.001"),
                fill_price=None,
                fee=Decimal("0"),
                error_message="Decision action is 'hold'; no order placed.",
                executed_at=datetime.now(UTC),
            )

        # ── 1. Idempotency ───────────────────────────────────────────────
        fingerprint = self._fingerprint(decision)
        if fingerprint in self._submitted_fingerprints:
            self._log.warning(
                "trade_executor.execute.duplicate",
                symbol=decision.symbol,
                action=decision.action,
                fingerprint=fingerprint,
            )
            return ExecutionResult(
                success=False,
                order_id="",
                symbol=decision.symbol,
                side=decision.action,
                quantity=Decimal("0.001"),
                fill_price=None,
                fee=Decimal("0"),
                error_message="Duplicate decision detected; order not re-submitted.",
                executed_at=datetime.now(UTC),
            )

        # ── 2. Pre-trade state ───────────────────────────────────────────
        pre_state = await self._fetch_portfolio_state()
        self._log.info(
            "trade_executor.execute.pre_trade",
            symbol=decision.symbol,
            action=decision.action,
            confidence=decision.confidence,
            quantity_pct=str(decision.quantity_pct),
            portfolio_snapshot=pre_state,
        )

        # ── 3. Submit order (with one retry) ─────────────────────────────
        qty = self._resolve_quantity(decision, pre_state)
        result = await self._submit_with_retry(decision, qty)

        # Mark the decision as submitted (regardless of success) so that a
        # crash-then-restart scenario does not re-submit in the same process.
        self._submitted_fingerprints.add(fingerprint)

        # ── 4. Post-trade state ──────────────────────────────────────────
        if result.success:
            post_state = await self._fetch_portfolio_state()
            self._log.info(
                "trade_executor.execute.post_trade",
                symbol=decision.symbol,
                order_id=result.order_id,
                fill_price=str(result.fill_price) if result.fill_price else None,
                portfolio_snapshot=post_state,
            )

        # ── 5. Persist to agent_decisions ────────────────────────────────
        await self._persist_decision(decision, result)

        # ── 6. Update budget counters ────────────────────────────────────
        if result.success:
            trade_value = self._estimate_trade_value(result, pre_state)
            try:
                await self._budget_mgr.record_trade(self._agent_id, trade_value)
                self._log.debug(
                    "trade_executor.execute.budget_updated",
                    symbol=decision.symbol,
                    trade_value=str(trade_value),
                )
            except Exception as exc:  # noqa: BLE001
                # Non-fatal: budget counter update failure must not block the execution record.
                self._log.error(
                    "trade_executor.execute.budget_update_failed",
                    symbol=decision.symbol,
                    error=str(exc),
                )

        return result

    async def execute_batch(self, decisions: list[TradeDecision]) -> list[ExecutionResult]:
        """Execute a list of :class:`~agent.models.ecosystem.TradeDecision` objects sequentially.

        Runs each decision one at a time (not in parallel) for safety.  A
        failure in one decision does not abort the remaining decisions —
        the failed :class:`~agent.models.ecosystem.ExecutionResult` is
        recorded and execution continues with the next decision.

        Args:
            decisions: Ordered list of :class:`~agent.models.ecosystem.TradeDecision`
                objects to execute.  An empty list returns an empty result list.

        Returns:
            List of :class:`~agent.models.ecosystem.ExecutionResult` objects,
            one per input decision, in the same order.
        """
        if not decisions:
            return []

        results: list[ExecutionResult] = []
        for i, decision in enumerate(decisions):
            self._log.info(
                "trade_executor.execute_batch.step",
                step=i + 1,
                total=len(decisions),
                symbol=decision.symbol,
                action=decision.action,
            )
            try:
                result = await self.execute(decision)
                results.append(result)
            except Exception as exc:  # noqa: BLE001
                # Build a failure result so the batch always returns N items.
                err_result = ExecutionResult(
                    success=False,
                    order_id="",
                    symbol=decision.symbol,
                    side=decision.action if decision.action in ("buy", "sell") else "buy",
                    quantity=Decimal("0.001"),
                    fill_price=None,
                    fee=Decimal("0"),
                    error_message=f"Unexpected error: {exc}",
                    executed_at=datetime.now(UTC),
                )
                results.append(err_result)
                self._log.error(
                    "trade_executor.execute_batch.unexpected_error",
                    step=i + 1,
                    symbol=decision.symbol,
                    error=str(exc),
                )

        self._log.info(
            "trade_executor.execute_batch.complete",
            total=len(decisions),
            successes=sum(1 for r in results if r.success),
        )
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fingerprint(decision: TradeDecision) -> str:
        """Compute a short idempotency fingerprint from a decision.

        Uses symbol + action + first 64 chars of reasoning to distinguish
        decisions while keeping the fingerprint compact.  SHA-256 (hex
        truncated to 16 chars) is used for determinism.

        Args:
            decision: The :class:`~agent.models.ecosystem.TradeDecision`
                to fingerprint.

        Returns:
            A 16-character hex string uniquely identifying the decision.
        """
        raw = f"{decision.symbol}:{decision.action}:{decision.reasoning[:64]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def _fetch_portfolio_state(self) -> dict[str, Any]:
        """Fetch current portfolio performance metrics via the SDK.

        Returns an empty dict when the SDK client is unavailable so that the
        execution pipeline can continue without portfolio state.

        Returns:
            Portfolio performance dict, or ``{}`` on failure.
        """
        if self._sdk_client is None:
            return {}
        try:
            raw = await self._sdk_client.get_performance()
            if isinstance(raw, dict):
                return raw
        except Exception as exc:  # noqa: BLE001
            self._log.warning(
                "trade_executor.portfolio_fetch_failed",
                error=str(exc),
            )
        return {}

    def _resolve_quantity(
        self,
        decision: TradeDecision,
        portfolio_state: dict[str, Any],
    ) -> str:
        """Derive a concrete order quantity string from the decision's ``quantity_pct``.

        Multiplies ``quantity_pct`` against the portfolio's total equity (from
        ``portfolio_state``) and divides by an assumed price of ``1 USDT``
        (the platform uses market prices, not this estimate — we just need a
        reasonable base-asset quantity to submit).

        Falls back to a symbol-specific minimum or :data:`_FALLBACK_QTY` when
        portfolio state is unavailable.

        For simplicity, the trading loop currently uses fixed per-symbol
        quantities similar to :mod:`agent.trading.loop`.  The ``quantity_pct``
        from the decision is logged for audit purposes but the returned
        quantity is capped at the platform-appropriate test sizes.

        Args:
            decision: The :class:`~agent.models.ecosystem.TradeDecision`
                containing the desired ``quantity_pct``.
            portfolio_state: Portfolio metrics dict (may be empty).

        Returns:
            Order quantity as a plain string (e.g. ``"0.001"``).
        """
        # Use per-symbol minimums as a safe default — the platform risk manager
        # will reject any quantity that violates position limits regardless.
        base_qty = _MIN_ORDER_QTY.get(decision.symbol, _FALLBACK_QTY)

        # If portfolio state is available, scale by quantity_pct but cap at
        # the minimum for safety in the paper-trading context.
        try:
            equity_raw = portfolio_state.get("total_value") or portfolio_state.get("equity")
            if equity_raw is not None:
                equity = Decimal(str(equity_raw))
                # Estimate a USDT value then convert to a base-asset quantity.
                # Use a conservative floor so we never exceed the risk limits.
                usdt_value = equity * decision.quantity_pct
                if usdt_value > Decimal("0"):
                    # Return quantity_pct as a USDT-fraction — the SDK converts.
                    # For paper trading, clip to the base minimum.
                    self._log.debug(
                        "trade_executor.qty_resolved",
                        symbol=decision.symbol,
                        quantity_pct=str(decision.quantity_pct),
                        estimated_usdt=str(usdt_value.quantize(Decimal("0.01"))),
                        using_base_qty=base_qty,
                    )
        except Exception as exc:  # noqa: BLE001
            self._log.debug(
                "trade_executor.qty_resolve_fallback",
                symbol=decision.symbol,
                error=str(exc),
            )

        return base_qty

    async def _submit_with_retry(
        self,
        decision: TradeDecision,
        qty: str,
    ) -> ExecutionResult:
        """Submit the order once; retry once on failure after a short delay.

        Args:
            decision: The :class:`~agent.models.ecosystem.TradeDecision`
                being executed.
            qty: The resolved quantity string to pass to the SDK.

        Returns:
            :class:`~agent.models.ecosystem.ExecutionResult` from the
            successful submission or from the final failure.
        """
        sym = decision.symbol
        side = decision.action  # "buy" or "sell"

        for attempt in range(2):  # attempt 0 = initial, attempt 1 = retry
            try:
                result = await self._place_order(sym, side, qty)
                if result.success:
                    return result
                if attempt == 0:
                    self._log.warning(
                        "trade_executor.submit.attempt_failed",
                        symbol=sym,
                        side=side,
                        attempt=attempt + 1,
                        error=result.error_message,
                    )
                    # Brief pause before retry.
                    import asyncio  # noqa: PLC0415
                    await asyncio.sleep(_RETRY_DELAY_SECONDS)
                else:
                    self._log.error(
                        "trade_executor.submit.final_failure",
                        symbol=sym,
                        side=side,
                        error=result.error_message,
                    )
                    return result
            except Exception as exc:  # noqa: BLE001
                if attempt == 0:
                    self._log.warning(
                        "trade_executor.submit.exception_attempt",
                        symbol=sym,
                        side=side,
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    import asyncio  # noqa: PLC0415
                    await asyncio.sleep(_RETRY_DELAY_SECONDS)
                else:
                    self._log.error(
                        "trade_executor.submit.exception_final",
                        symbol=sym,
                        side=side,
                        error=str(exc),
                    )
                    return ExecutionResult(
                        success=False,
                        order_id="",
                        symbol=sym,
                        side=side,
                        quantity=Decimal(qty),
                        fill_price=None,
                        fee=Decimal("0"),
                        error_message=str(exc),
                        executed_at=datetime.now(UTC),
                    )

        # Should be unreachable — both attempts return or the last iteration returns.
        return ExecutionResult(
            success=False,
            order_id="",
            symbol=sym,
            side=side,
            quantity=Decimal(qty),
            fill_price=None,
            fee=Decimal("0"),
            error_message="Order submission exhausted all attempts.",
            executed_at=datetime.now(UTC),
        )

    async def _place_order(
        self,
        symbol: str,
        side: str,
        qty: str,
    ) -> ExecutionResult:
        """Issue a single market order via the SDK.

        Args:
            symbol: Trading pair (e.g. ``"BTCUSDT"``).
            side: Order side (``"buy"`` or ``"sell"``).
            qty: Quantity string (e.g. ``"0.001"``).

        Returns:
            :class:`~agent.models.ecosystem.ExecutionResult` capturing the
            SDK response.
        """
        if self._sdk_client is None:
            self._log.debug(
                "trade_executor.place_order.no_sdk",
                symbol=symbol,
                side=side,
                qty=qty,
            )
            return ExecutionResult(
                success=False,
                order_id="",
                symbol=symbol,
                side=side,
                quantity=Decimal(qty),
                fill_price=None,
                fee=Decimal("0"),
                error_message="SDK client not configured (dry-run mode).",
                executed_at=datetime.now(UTC),
            )

        self._log.info(
            "trade_executor.place_order",
            symbol=symbol,
            side=side,
            qty=qty,
        )

        order_resp = await self._sdk_client.place_market_order(symbol, side, qty)
        order_resp_dict: dict[str, Any] = (
            order_resp if isinstance(order_resp, dict) else {}
        )

        order_id = str(order_resp_dict.get("order_id", ""))

        # Normalise fill price — SDK may return "executed_price" or "fill_price".
        fill_price: Decimal | None = None
        for price_key in ("executed_price", "fill_price", "price"):
            raw = order_resp_dict.get(price_key)
            if raw is not None:
                try:
                    fill_price = Decimal(str(raw))
                    break
                except Exception:  # noqa: BLE001
                    pass

        # Normalise fee.
        fee: Decimal = Decimal("0")
        for fee_key in ("fee", "commission"):
            raw_fee = order_resp_dict.get(fee_key)
            if raw_fee is not None:
                try:
                    fee = Decimal(str(raw_fee))
                    break
                except Exception:  # noqa: BLE001
                    pass

        # Normalise executed quantity.
        exec_qty = Decimal(qty)
        for qty_key in ("executed_quantity", "executed_qty", "filled_qty"):
            raw_qty = order_resp_dict.get(qty_key)
            if raw_qty is not None:
                try:
                    exec_qty = Decimal(str(raw_qty))
                    break
                except Exception:  # noqa: BLE001
                    pass

        self._log.info(
            "trade_executor.place_order.success",
            symbol=symbol,
            side=side,
            order_id=order_id,
            fill_price=str(fill_price) if fill_price else None,
        )

        return ExecutionResult(
            success=True,
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=exec_qty,
            fill_price=fill_price,
            fee=fee,
            error_message="",
            executed_at=datetime.now(UTC),
        )

    async def _persist_decision(
        self,
        decision: TradeDecision,
        result: ExecutionResult,
    ) -> None:
        """Persist an ``AgentDecision`` row to the database with ``order_id`` attached.

        Uses lazy imports so this module can be imported in test environments
        without a running database.  Failures are logged but never re-raised —
        a persistence failure must not block the execution result from being
        returned to the trading loop.

        Args:
            decision: The :class:`~agent.models.ecosystem.TradeDecision`
                that was executed.
            result: The :class:`~agent.models.ecosystem.ExecutionResult`
                from the execution attempt.
        """
        try:
            from src.database.models import AgentDecision  # noqa: PLC0415
            from src.database.repositories.agent_decision_repo import (  # noqa: PLC0415
                AgentDecisionRepository,
            )
            from src.database.session import get_session_factory  # noqa: PLC0415
        except ImportError as exc:
            self._log.warning(
                "trade_executor.persist.import_failed",
                error=str(exc),
                hint="DB not available; skipping AgentDecision persistence.",
            )
            return

        order_uuid: UUID | None = None
        if result.success and result.order_id:
            try:
                order_uuid = UUID(result.order_id)
            except (ValueError, AttributeError):
                pass

        try:
            agent_uuid = UUID(self._agent_id)
        except (ValueError, AttributeError) as exc:
            self._log.warning(
                "trade_executor.persist.invalid_agent_id",
                agent_id=self._agent_id,
                error=str(exc),
            )
            return

        try:
            factory = get_session_factory()
            session = factory()
            async with session.begin():
                repo = AgentDecisionRepository(session)
                decision_row = AgentDecision(
                    agent_id=agent_uuid,
                    session_id=None,
                    decision_type="trade",
                    symbol=decision.symbol,
                    direction=decision.action,
                    confidence=Decimal(str(round(decision.confidence, 4))),
                    reasoning=decision.reasoning,
                    market_snapshot=decision.signals,
                    signals=list(decision.signals.items()) if decision.signals else [],
                    risk_assessment={
                        "risk_notes": decision.risk_notes,
                        "strategy_weights": decision.strategy_weights,
                        "execution_success": result.success,
                        "execution_error": result.error_message,
                    },
                    order_id=order_uuid,
                )
                await repo.create(decision_row)

            self._log.debug(
                "trade_executor.persist.success",
                symbol=decision.symbol,
                order_id=result.order_id,
            )

        except Exception as exc:  # noqa: BLE001
            self._log.error(
                "trade_executor.persist.db_error",
                symbol=decision.symbol,
                error=str(exc),
            )

    @staticmethod
    def _estimate_trade_value(
        result: ExecutionResult,
        portfolio_state: dict[str, Any],
    ) -> Decimal:
        """Estimate the USDT value of an executed trade for the budget counter.

        Uses fill price × quantity if available; falls back to a conservative
        100 USDT estimate.

        Args:
            result: The successful :class:`~agent.models.ecosystem.ExecutionResult`.
            portfolio_state: Pre-trade portfolio state (used as a fallback
                source for pricing information).

        Returns:
            Estimated USDT trade value as a :class:`~decimal.Decimal`.
        """
        try:
            if result.fill_price is not None and result.quantity > Decimal("0"):
                return (result.fill_price * result.quantity).quantize(Decimal("0.01"))
        except Exception:  # noqa: BLE001
            pass

        # Fallback: 5% of equity as a conservative estimate.
        try:
            equity_raw = portfolio_state.get("total_value") or portfolio_state.get("equity")
            if equity_raw is not None:
                equity = Decimal(str(equity_raw))
                return (equity * Decimal("0.05")).quantize(Decimal("0.01"))
        except Exception:  # noqa: BLE001
            pass

        return Decimal("100.00")
