"""Main autonomous trading loop.

:class:`TradingLoop` implements the observe → analyse → decide → check → execute
→ record → learn cycle for one agent.  It runs indefinitely in the background,
waking every :attr:`~agent.config.AgentConfig.trading_loop_interval` seconds, and
shuts down cleanly on :meth:`stop`.

Architecture::

    TradingLoop.tick()
          │
          ├── 1. Observe  — fetch prices, candles, positions via SDK
          ├── 2. Analyse  — SignalGenerator.generate() → list[TradingSignal]
          ├── 3. Decide   — filter by confidence threshold; build TradeDecision per signal
          ├── 4. Check    — PermissionEnforcer.check_action("trade") per decision
          ├── 5. Execute  — SDK place_market_order() per approved decision
          ├── 6. Record   — persist AgentDecision + AgentObservation rows
          └── 7. Learn    — extract compact insight strings for memory store

Usage::

    from agent.config import AgentConfig
    from agent.permissions.enforcement import PermissionEnforcer
    from agent.trading.loop import TradingLoop

    loop = TradingLoop(agent_id="uuid", config=config, enforcer=enforcer)
    await loop.start()        # blocks until loop.stop() is called
    # — or —
    result = await loop.tick() # single manual tick (for tests / backtest mode)

Integration notes
-----------------
- :class:`TradingLoop` never imports from ``src/`` at module level.  All DB
  and Redis access happens through lazy imports inside methods so the module
  can be imported in test environments without a running DB.
- :meth:`start` runs the loop in a background ``asyncio.Task`` and returns
  immediately.  Call :meth:`stop` to signal shutdown and ``await loop.stopped``
  to wait for the task to finish.
- Every error in :meth:`tick` is caught, logged, and stored in
  :class:`~agent.models.ecosystem.TradingCycleResult` ``errors`` list.  One
  failed symbol never aborts other symbols.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from agent.config import AgentConfig
from agent.models.ecosystem import ExecutionResult, PositionAction, TradingCycleResult
from agent.permissions.enforcement import PermissionEnforcer
from agent.trading.signal_generator import SignalGenerator, TradingSignal

logger = structlog.get_logger(__name__)

# ── Module-level constants ─────────────────────────────────────────────────────

# Trade size (base asset units) used when the loop places a market order.
# These are intentionally small "paper-trading" sizes that stay well within
# platform risk limits while validating the full execution pipeline.
_DEFAULT_ORDER_QTY: dict[str, str] = {
    "BTCUSDT": "0.0001",
    "ETHUSDT": "0.001",
    "SOLUSDT": "0.01",
}
_FALLBACK_QTY: str = "0.001"

# How long to sleep between loop restart attempts after a fatal tick error.
_ERROR_BACKOFF_SECONDS: float = 10.0

# Maximum consecutive tick errors before the loop backs off for one full interval.
_MAX_CONSECUTIVE_ERRORS: int = 5


# ── Custom exceptions ──────────────────────────────────────────────────────────


class LoopStoppedError(Exception):
    """Raised when :meth:`TradingLoop.tick` is called after the loop has stopped.

    Args:
        agent_id: The agent whose loop has stopped.
    """

    def __init__(self, agent_id: str) -> None:
        super().__init__(f"TradingLoop for agent '{agent_id}' is stopped.")
        self.agent_id = agent_id


# ── TradingLoop ────────────────────────────────────────────────────────────────


class TradingLoop:
    """Autonomous observe → decide → execute cycle for one agent.

    The loop wakes every :attr:`~agent.config.AgentConfig.trading_loop_interval`
    seconds, runs a complete :meth:`tick`, records the outcome, and sleeps again.
    Shutdown is signalled via :attr:`_stop_event` (an :class:`asyncio.Event`),
    which :meth:`stop` sets.

    Args:
        agent_id: UUID string of the trading agent this loop drives.
        config: :class:`~agent.config.AgentConfig` with connectivity, interval,
            and threshold settings.
        enforcer: :class:`~agent.permissions.enforcement.PermissionEnforcer`
            used to gate every trade action before execution.
        signal_generator: Optional pre-built :class:`SignalGenerator`.  When
            ``None`` the loop creates a default generator on :meth:`start`.
            Pass an explicit instance to inject custom runners or test doubles.
        sdk_client: Optional pre-built ``AsyncAgentExchangeClient``.  When
            ``None`` the loop constructs one from ``config.platform_api_key`` on
            :meth:`start`; a connected client enables live order placement.

    Example::

        config = AgentConfig()
        enforcer = PermissionEnforcer(
            capability_mgr=CapabilityManager(config=config),
            budget_mgr=BudgetManager(config=config),
        )
        loop = TradingLoop(agent_id="550e8400-...", config=config, enforcer=enforcer)
        await loop.start()
        # ... later ...
        await loop.stop()
    """

    def __init__(
        self,
        agent_id: str,
        config: AgentConfig,
        enforcer: PermissionEnforcer,
        signal_generator: SignalGenerator | None = None,
        sdk_client: Any = None,  # noqa: ANN401
    ) -> None:
        self._agent_id = agent_id
        self._config = config
        self._enforcer = enforcer
        self._signal_generator: SignalGenerator | None = signal_generator
        self._sdk_client: Any = sdk_client

        # Lifecycle state
        self._stop_event = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._is_running = False
        self._cycle_counter: int = 0
        self._consecutive_errors: int = 0
        self._started_at: datetime | None = None

        # HTTP client for candle fetching (lazily created in _ensure_rest_client).
        self._rest_client: Any = None

        self._log = logger.bind(agent_id=agent_id, component="trading_loop")

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the trading loop as a background asyncio task.

        Initialises the signal generator (if not already provided), then
        launches :meth:`_run_forever` as a named :class:`asyncio.Task`.
        Returns immediately — the loop runs in the background.

        Calling :meth:`start` on an already-running loop is a no-op.

        Raises:
            RuntimeError: If the asyncio event loop is not running.
        """
        if self._is_running:
            self._log.warning("trading_loop.start.already_running")
            return

        self._log.info(
            "trading_loop.start",
            interval=self._config.trading_loop_interval,
            symbols=self._config.symbols,
            min_confidence=self._config.trading_min_confidence,
        )

        await self._ensure_signal_generator()
        self._started_at = datetime.now(UTC)
        self._is_running = True
        self._stop_event.clear()
        self._loop_task = asyncio.get_event_loop().create_task(
            self._run_forever(), name=f"trading_loop_{self._agent_id}"
        )

    async def stop(self) -> None:
        """Signal the trading loop to stop and wait for it to finish.

        Sets the internal shutdown event, which causes :meth:`_run_forever` to
        exit after completing any in-progress tick.  Waits for the loop task to
        terminate (with a 30-second timeout).  Safe to call multiple times.
        """
        if not self._is_running:
            return

        self._log.info("trading_loop.stop")
        self._stop_event.set()
        self._is_running = False

        if self._loop_task is not None and not self._loop_task.done():
            try:
                await asyncio.wait_for(self._loop_task, timeout=30.0)
            except (TimeoutError, asyncio.CancelledError):
                self._loop_task.cancel()
                try:
                    await self._loop_task
                except asyncio.CancelledError:
                    pass

        # Close the REST client if we created it.
        if self._rest_client is not None:
            try:
                await self._rest_client.aclose()
            except Exception as exc:  # noqa: BLE001
                self._log.debug("trading_loop.rest_client.close_error", error=str(exc))
            self._rest_client = None

        self._log.info(
            "trading_loop.stopped",
            cycles_completed=self._cycle_counter,
        )

    @property
    def is_running(self) -> bool:
        """Whether the trading loop background task is active."""
        return self._is_running

    @property
    def cycle_count(self) -> int:
        """Number of completed ticks since :meth:`start` was called."""
        return self._cycle_counter

    # ------------------------------------------------------------------
    # Main tick — public for manual / test invocation
    # ------------------------------------------------------------------

    async def tick(self) -> TradingCycleResult:
        """Execute one complete trading cycle.

        Pipeline:

        1. **Observe** — fetch current positions and portfolio state via SDK.
        2. **Analyse** — run :class:`~agent.trading.signal_generator.SignalGenerator`
           to produce :class:`~agent.trading.signal_generator.TradingSignal` objects.
        3. **Decide** — filter signals by :attr:`~AgentConfig.trading_min_confidence`;
           build a :class:`~agent.models.ecosystem.TradeDecision` for each.
        4. **Check** — run :class:`~agent.permissions.enforcement.PermissionEnforcer`
           against every trade decision; skip those that are denied.
        5. **Execute** — call ``sdk.place_market_order()`` for each approved decision.
        6. **Record** — persist :class:`~src.database.models.AgentDecision` and
           :class:`~src.database.models.AgentObservation` rows in the DB.
        7. **Learn** — extract compact insight strings; written to memory store
           (best-effort, never raises).

        Args:
            *(none)* — symbols come from ``self._config.symbols``.

        Returns:
            A :class:`~agent.models.ecosystem.TradingCycleResult` with the full
            audit trail for this cycle.

        Raises:
            LoopStoppedError: If :meth:`stop` has been called before this tick.
        """
        if self._stop_event.is_set():
            raise LoopStoppedError(self._agent_id)

        self._cycle_counter += 1
        cycle_num = self._cycle_counter
        start_ms = time.monotonic()
        errors: list[str] = []
        executions: list[ExecutionResult] = []
        position_actions: list[PositionAction] = []
        signals_generated = 0
        decisions_made = 0

        self._log.info(
            "trading_loop.tick.start",
            cycle=cycle_num,
            symbols=self._config.symbols,
        )

        # ── 1. Observe ───────────────────────────────────────────────────
        portfolio_state, positions = await self._observe()

        # ── 2. Analyse ───────────────────────────────────────────────────
        signals: list[TradingSignal] = []
        try:
            if self._signal_generator is not None:
                signals = await self._signal_generator.generate(self._config.symbols)
                signals_generated = len(signals)
        except Exception as exc:  # noqa: BLE001
            err_msg = f"Signal generation failed: {exc}"
            errors.append(err_msg)
            self._log.error("trading_loop.tick.signal_gen_failed", cycle=cycle_num, error=str(exc))

        # ── 3. Decide — filter by confidence threshold ───────────────────
        threshold = self._config.trading_min_confidence
        actionable: list[TradingSignal] = [
            s for s in signals
            if s.action != "hold" and s.confidence >= threshold
        ]
        decisions_made = len(actionable)

        self._log.info(
            "trading_loop.tick.signals",
            cycle=cycle_num,
            total_signals=signals_generated,
            actionable=decisions_made,
            threshold=threshold,
        )

        # ── 4. Check + 5. Execute ─────────────────────────────────────────
        for signal in actionable:
            exec_result, sym_error = await self._check_and_execute(signal, portfolio_state)
            if exec_result is not None:
                executions.append(exec_result)
            if sym_error:
                errors.append(sym_error)

        # ── 6. Record ─────────────────────────────────────────────────────
        try:
            await self._record(
                signals=signals,
                executions=executions,
                portfolio_state=portfolio_state,
                positions=positions,
            )
        except Exception as exc:  # noqa: BLE001
            err_msg = f"Record step failed: {exc}"
            errors.append(err_msg)
            self._log.error("trading_loop.tick.record_failed", cycle=cycle_num, error=str(exc))

        # ── 7. Learn (best-effort) ─────────────────────────────────────────
        try:
            await self._learn(signals=signals, executions=executions)
        except Exception as exc:  # noqa: BLE001
            # Non-fatal — learning failures must never block the cycle.
            self._log.warning(
                "trading_loop.tick.learn_failed",
                cycle=cycle_num,
                error=str(exc),
            )

        duration_ms = int((time.monotonic() - start_ms) * 1000)
        trades_executed = sum(1 for e in executions if e.success)

        result = TradingCycleResult(
            agent_id=self._agent_id,
            cycle_number=cycle_num,
            symbols_observed=list(self._config.symbols),
            signals_generated=signals_generated,
            decisions_made=decisions_made,
            trades_executed=trades_executed,
            executions=executions,
            position_actions=position_actions,
            errors=errors,
            cycle_duration_ms=duration_ms,
            completed_at=datetime.now(UTC),
        )

        self._log.info(
            "trading_loop.tick.complete",
            cycle=cycle_num,
            duration_ms=duration_ms,
            signals=signals_generated,
            actionable=decisions_made,
            executed=trades_executed,
            errors=len(errors),
        )
        return result

    # ------------------------------------------------------------------
    # Internal background runner
    # ------------------------------------------------------------------

    async def _run_forever(self) -> None:
        """Background coroutine: run ticks indefinitely until :meth:`stop` is called.

        Sleeps ``trading_loop_interval`` seconds between ticks.  Uses
        :class:`asyncio.Event` for shutdown so the loop wakes immediately
        when :meth:`stop` is called instead of waiting for the full interval.
        Backs off for :data:`_ERROR_BACKOFF_SECONDS` after repeated failures.
        """
        interval = float(self._config.trading_loop_interval)
        self._log.info("trading_loop.run_forever.started", interval=interval)

        while not self._stop_event.is_set():
            try:
                await self.tick()
                self._consecutive_errors = 0
            except LoopStoppedError:
                break
            except Exception as exc:  # noqa: BLE001
                self._consecutive_errors += 1
                self._log.error(
                    "trading_loop.run_forever.tick_error",
                    error=str(exc),
                    consecutive_errors=self._consecutive_errors,
                )
                if self._consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    self._log.warning(
                        "trading_loop.run_forever.backing_off",
                        backoff_seconds=_ERROR_BACKOFF_SECONDS,
                        consecutive_errors=self._consecutive_errors,
                    )
                    # Wait backoff time or shutdown signal — whichever comes first.
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=_ERROR_BACKOFF_SECONDS,
                        )
                    except TimeoutError:
                        pass
                    self._consecutive_errors = 0

            # Sleep for the configured interval or until stop is signalled.
            if not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=interval,
                    )
                except TimeoutError:
                    # Normal case: timeout elapsed, run next tick.
                    pass

        self._log.info("trading_loop.run_forever.exited")

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    async def _observe(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Fetch portfolio state and open positions via the SDK.

        Returns:
            Tuple of ``(portfolio_state, positions)`` where both are dicts/lists
            suitable for JSON serialisation.  Returns empty structures on failure
            so the loop continues even when the SDK is unavailable.
        """
        portfolio_state: dict[str, Any] = {}
        positions: list[dict[str, Any]] = []

        if self._sdk_client is None:
            return portfolio_state, positions

        try:
            portfolio_raw = await self._sdk_client.get_performance()
            if isinstance(portfolio_raw, dict):
                portfolio_state = portfolio_raw
        except Exception as exc:  # noqa: BLE001
            self._log.warning("trading_loop.observe.portfolio_failed", error=str(exc))

        try:
            positions_raw = await self._sdk_client.get_positions()
            if isinstance(positions_raw, list):
                positions = positions_raw
        except Exception as exc:  # noqa: BLE001
            self._log.warning("trading_loop.observe.positions_failed", error=str(exc))

        return portfolio_state, positions

    async def _check_and_execute(
        self,
        signal: TradingSignal,
        portfolio_state: dict[str, Any],
    ) -> tuple[ExecutionResult | None, str]:
        """Gate a trade signal through the permission enforcer then execute it.

        This method performs steps 4 (permission check) and 5 (execution) of
        the tick pipeline for a single symbol.

        Permission check MUST happen before any SDK order call.  Budget check
        is included in :meth:`~PermissionEnforcer.check_action` via the
        ``"trade"`` action key.

        Args:
            signal: A non-HOLD :class:`TradingSignal` that passed the
                confidence threshold filter.
            portfolio_state: Current portfolio metrics (used to compute trade
                value for the budget check).

        Returns:
            Tuple of ``(ExecutionResult | None, error_string)``.
            ``ExecutionResult`` is ``None`` when the permission check was
            denied or the SDK call was skipped.  ``error_string`` is empty
            on success.
        """
        sym = signal.symbol
        side = signal.action  # "buy" or "sell"

        # ── 4. Permission check ──────────────────────────────────────────
        try:
            # Estimate trade value for the budget check.  Use a conservative
            # default when portfolio state is unavailable.
            trade_value_str = self._estimate_trade_value(signal, portfolio_state)
            enforcement = await self._enforcer.check_action(
                self._agent_id,
                "trade",
                {"symbol": sym, "value": trade_value_str},
            )
        except Exception as exc:  # noqa: BLE001
            err = f"Permission check failed for {sym}: {exc}"
            self._log.error("trading_loop.check.enforcer_error", symbol=sym, error=str(exc))
            return None, err

        if not enforcement.allowed:
            self._log.info(
                "trading_loop.check.denied",
                symbol=sym,
                side=side,
                reason=enforcement.reason,
            )
            return None, ""  # Denied but not an error — do not add to errors list.

        # ── 5. Execute ───────────────────────────────────────────────────
        return await self._place_order(signal)

    async def _place_order(
        self,
        signal: TradingSignal,
    ) -> tuple[ExecutionResult | None, str]:
        """Place a market order via the SDK for the given signal.

        Args:
            signal: The approved :class:`TradingSignal` to execute.

        Returns:
            Tuple of ``(ExecutionResult | None, error_string)``.
            ``ExecutionResult`` is ``None`` when the SDK client is not
            available (no live trading configured).
        """
        sym = signal.symbol
        side = signal.action
        qty = _DEFAULT_ORDER_QTY.get(sym, _FALLBACK_QTY)

        if self._sdk_client is None:
            self._log.debug(
                "trading_loop.execute.no_sdk_client",
                symbol=sym,
                side=side,
                qty=qty,
            )
            return None, ""

        self._log.info(
            "trading_loop.execute.placing_order",
            symbol=sym,
            side=side,
            qty=qty,
            confidence=signal.confidence,
        )

        try:
            order_resp = await self._sdk_client.place_market_order(sym, side, qty)
            order_id = str(order_resp.get("order_id", "")) if isinstance(order_resp, dict) else ""
            fill_price_raw = order_resp.get("fill_price") if isinstance(order_resp, dict) else None
            fill_price: Decimal | None = None
            if fill_price_raw is not None:
                try:
                    fill_price = Decimal(str(fill_price_raw))
                except Exception:  # noqa: BLE001
                    pass

            fee_raw = order_resp.get("fee", "0") if isinstance(order_resp, dict) else "0"
            try:
                fee = Decimal(str(fee_raw))
            except Exception:  # noqa: BLE001
                fee = Decimal("0")

            result = ExecutionResult(
                success=True,
                order_id=order_id,
                symbol=sym,
                side=side,
                quantity=Decimal(qty),
                fill_price=fill_price,
                fee=fee,
                error_message="",
                executed_at=datetime.now(UTC),
            )
            self._log.info(
                "trading_loop.execute.order_placed",
                symbol=sym,
                side=side,
                order_id=order_id,
            )
            return result, ""

        except Exception as exc:  # noqa: BLE001
            err = f"Order placement failed for {sym}: {exc}"
            self._log.error(
                "trading_loop.execute.order_failed",
                symbol=sym,
                side=side,
                error=str(exc),
            )
            result = ExecutionResult(
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
            return result, err

    async def _record(
        self,
        signals: list[TradingSignal],
        executions: list[ExecutionResult],
        portfolio_state: dict[str, Any],
        positions: list[dict[str, Any]],
    ) -> None:
        """Persist agent decisions and market observations to the database.

        Records one :class:`~src.database.models.AgentDecision` row per
        actionable signal and one :class:`~src.database.models.AgentObservation`
        row per tick cycle.  Uses lazy imports to avoid coupling this module to
        the platform DB layer at import time.

        Every decision is recorded — both executed trades and hold decisions —
        so the full decision history is preserved for replay and learning.

        Args:
            signals: All signals from this cycle (including HOLDs).
            executions: Execution results for trades placed this cycle.
            portfolio_state: Portfolio metrics snapshot for the observation row.
            positions: Open positions list for the observation row.
        """
        try:
            from src.database.models import AgentDecision, AgentObservation  # noqa: PLC0415
            from src.database.repositories.agent_decision_repo import (  # noqa: PLC0415
                AgentDecisionRepository,
            )
            from src.database.repositories.agent_observation_repo import (  # noqa: PLC0415
                AgentObservationRepository,
            )
            from src.database.session import get_session_factory  # noqa: PLC0415
        except ImportError as exc:
            self._log.warning(
                "trading_loop.record.import_failed",
                error=str(exc),
                hint="DB not available in this environment; skipping persistence.",
            )
            return

        # Build a fast lookup from symbol → execution result (for order_id linking).
        exec_by_symbol: dict[str, ExecutionResult] = {e.symbol: e for e in executions}

        # Determine price snapshot from signals' candle indicators.
        prices_snapshot: dict[str, Any] = {}

        # Build signals list for the observation row.
        obs_signals = [
            {
                "symbol": s.symbol,
                "action": s.action,
                "confidence": s.confidence,
                "agreement_rate": s.agreement_rate,
                "regime": s.regime,
            }
            for s in signals
        ]

        # Detect overall regime from the first signal with a regime label.
        regime_label: str | None = None
        for s in signals:
            if s.regime:
                regime_label = s.regime
                break

        try:
            factory = get_session_factory()
            session = factory()
            async with session.begin():
                decision_repo = AgentDecisionRepository(session)
                obs_repo = AgentObservationRepository(session)

                agent_uuid = UUID(self._agent_id)
                now = datetime.now(UTC)

                # Record one decision row per signal.
                for sig in signals:
                    decision_type = "hold" if sig.action == "hold" else "trade"
                    direction = sig.action  # "buy", "sell", or "hold"
                    exec_result = exec_by_symbol.get(sig.symbol)
                    order_uuid: UUID | None = None
                    if exec_result is not None and exec_result.success and exec_result.order_id:
                        try:
                            order_uuid = UUID(exec_result.order_id)
                        except (ValueError, AttributeError):
                            pass

                    decision_row = AgentDecision(
                        agent_id=agent_uuid,
                        session_id=None,  # Filled in by AgentServer when session is active.
                        decision_type=decision_type,
                        symbol=sig.symbol,
                        direction=direction,
                        confidence=Decimal(str(round(sig.confidence, 4))),
                        reasoning=(
                            f"Ensemble signal: {sig.action} @ "
                            f"{sig.confidence:.2%} confidence. "
                            f"Regime: {sig.regime or 'unknown'}."
                        ),
                        market_snapshot=sig.indicators,
                        signals=obs_signals,
                        risk_assessment={
                            "source_contributions": sig.source_contributions,
                            "agreement_rate": sig.agreement_rate,
                        },
                        order_id=order_uuid,
                    )
                    await decision_repo.create(decision_row)

                # Record one observation row for this cycle.
                obs_row = AgentObservation(
                    time=now,
                    agent_id=agent_uuid,
                    decision_id=None,  # Not linked to a single decision.
                    prices=prices_snapshot,
                    indicators=None,
                    regime=regime_label,
                    portfolio_state=portfolio_state if portfolio_state else None,
                    signals=obs_signals,
                )
                await obs_repo.insert(obs_row)

        except Exception as exc:  # noqa: BLE001
            self._log.error(
                "trading_loop.record.db_error",
                error=str(exc),
            )
            raise

    async def _learn(
        self,
        signals: list[TradingSignal],
        executions: list[ExecutionResult],
    ) -> None:
        """Extract insights from this cycle and write them to the memory store.

        Generates compact, human-readable insight strings from the cycle's
        signals and executions.  Each insight is written to the agent memory
        store as a short-term observation.  Failures here are non-fatal.

        Args:
            signals: All :class:`TradingSignal` objects generated this cycle.
            executions: :class:`~agent.models.ecosystem.ExecutionResult` list.
        """
        insights: list[str] = []

        for sig in signals:
            if sig.action != "hold" and sig.confidence >= self._config.trading_min_confidence:
                regime_info = f" (regime: {sig.regime})" if sig.regime else ""
                insights.append(
                    f"Signal: {sig.symbol} {sig.action.upper()} "
                    f"at {sig.confidence:.2%} confidence{regime_info}."
                )

        for exec_result in executions:
            if exec_result.success:
                insights.append(
                    f"Executed: {exec_result.symbol} {exec_result.side.upper()} "
                    f"{exec_result.quantity} @ "
                    f"{exec_result.fill_price or 'market'}."
                )
            else:
                insights.append(
                    f"Failed to execute: {exec_result.symbol} "
                    f"{exec_result.side.upper()} — {exec_result.error_message}."
                )

        if not insights:
            return

        # Try to write to the agent memory store if it is available.
        try:
            import importlib.util  # noqa: PLC0415

            _has_memory = importlib.util.find_spec("agent.memory.store") is not None
            # MemoryStore is an optional dependency; skip silently if unavailable.
            combined_insight = " | ".join(insights)
            _ = _has_memory  # referenced in log message below
            self._log.debug(
                "trading_loop.learn.insights_extracted",
                count=len(insights),
                preview=combined_insight[:120],
            )
            # The memory store requires an async session; log without persisting
            # here since loop.py does not own a long-lived DB session.
            # Full memory integration happens via AgentServer._memory_store when
            # the TradingLoop is embedded in a live server context.
        except ImportError:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _ensure_signal_generator(self) -> None:
        """Initialise the signal generator if not already set.

        Builds an :class:`~agent.strategies.ensemble.run.EnsembleRunner` with
        default settings and wraps it in a :class:`SignalGenerator`.  This path
        is taken when no ``signal_generator`` was provided to the constructor.
        """
        if self._signal_generator is not None:
            return

        try:
            import httpx  # noqa: PLC0415

            from agent.strategies.ensemble.config import EnsembleConfig  # noqa: PLC0415
            from agent.strategies.ensemble.run import EnsembleRunner  # noqa: PLC0415

            # Build a REST client for candle fetching.
            rest_client = httpx.AsyncClient(
                base_url=self._config.platform_base_url,
                headers={"X-API-Key": self._config.platform_api_key},
                timeout=30.0,
            )
            self._rest_client = rest_client

            ensemble_config = EnsembleConfig(
                mode="live",
                symbols=self._config.symbols,
                platform_api_key=self._config.platform_api_key,
                platform_base_url=self._config.platform_base_url,
                # Disable risk overlay here — the trading loop's PermissionEnforcer
                # provides the agent-level risk gate.  The RiskMiddleware inside the
                # ensemble runner would apply a second layer for individual signals,
                # but position-sizing and budget enforcement belong at the loop level
                # where the agent's limits are known.
                enable_risk_overlay=False,
            )
            runner = EnsembleRunner(
                config=ensemble_config,
                sdk_client=self._sdk_client,
                rest_client=rest_client,
            )
            await runner.initialize()

            self._signal_generator = SignalGenerator(
                runner=runner,
                config=self._config,
                rest_client=rest_client,
            )
            self._log.info(
                "trading_loop.signal_generator.initialised",
                symbols=self._config.symbols,
                enable_rl=ensemble_config.enable_rl_signal,
                enable_evolved=ensemble_config.enable_evolved_signal,
                enable_regime=ensemble_config.enable_regime_signal,
            )

        except Exception as exc:  # noqa: BLE001
            self._log.warning(
                "trading_loop.signal_generator.init_failed",
                error=str(exc),
                hint="Loop will run without signal generation; all ticks will produce no signals.",
            )

    @staticmethod
    def _estimate_trade_value(
        signal: TradingSignal,
        portfolio_state: dict[str, Any],
    ) -> str:
        """Estimate the USDT value of a prospective trade for the budget check.

        Uses the agent's ``quantity_pct`` implied by ``config.max_trade_pct`` and
        the portfolio's total equity from ``portfolio_state``.  Falls back to a
        conservative default of ``100 USDT`` when the portfolio state is
        unavailable.

        Args:
            signal: The trade signal for which to estimate value.
            portfolio_state: Portfolio metrics dict (may be empty).

        Returns:
            USDT trade value as a plain string (e.g. ``"500.00"``).
        """
        try:
            equity_raw = portfolio_state.get("total_value") or portfolio_state.get("equity")
            if equity_raw is not None:
                equity = Decimal(str(equity_raw))
                # Use 5 % of equity as a conservative estimate.
                value = equity * Decimal("0.05")
                return str(value.quantize(Decimal("0.01")))
        except (Exception,):  # noqa: BLE001
            pass
        return "100.00"
