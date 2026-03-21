"""Position monitor — evaluates open positions and recommends exits.

:class:`PositionMonitor` fetches all open positions for an agent via the SDK,
evaluates each against stop-loss/take-profit thresholds and maximum holding
duration, and returns a list of :class:`~agent.models.ecosystem.PositionAction`
recommendations.  When actions are available, :meth:`execute_exits` submits
the corresponding close orders through a :class:`~agent.trading.execution.TradeExecutor`.

Architecture::

    PositionMonitor.check_positions(agent_id)
           │
           ├── Fetch open positions via SDK (get_positions)
           ├── For each position:
           │       ├── Compute unrealised PnL
           │       ├── Check stop-loss threshold
           │       ├── Check take-profit threshold
           │       ├── Check maximum holding duration
           │       └── Emit PositionAction (hold / partial_exit / full_exit)
           └── Return list[PositionAction]

    PositionMonitor.execute_exits(actions)
           │
           ├── Filter actions where action != "hold"
           ├── For each exit action:
           │       ├── Check permission (enforcer.check_action "close_position")
           │       └── Execute opposite-side market order via TradeExecutor
           └── Return list[ExecutionResult]

Usage::

    from agent.trading.monitor import PositionMonitor

    monitor = PositionMonitor(
        agent_id="uuid",
        config=config,
        enforcer=enforcer,
        executor=executor,
        sdk_client=sdk,
    )
    actions = await monitor.check_positions("uuid")
    results = await monitor.execute_exits(actions)

Configuration notes
-------------------
Stop-loss and take-profit thresholds are read from
:class:`~agent.config.AgentConfig`.  Defaults:

- ``stop_loss_pct`` — 5 % loss triggers full exit (``urgency="immediate"``).
- ``take_profit_pct`` — 20 % gain triggers full exit (``urgency="next_cycle"``).
- ``max_hold_seconds`` — 24 hours; positions held longer trigger full exit
  (``urgency="next_cycle"``).

These can be overridden at construction time via explicit keyword arguments
for fine-grained per-session control.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from agent.config import AgentConfig
from agent.models.ecosystem import ExecutionResult, PositionAction, TradeDecision
from agent.permissions.enforcement import PermissionEnforcer
from agent.trading.execution import TradeExecutor

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Defaults (overridable at construction)
# ---------------------------------------------------------------------------

# Fraction of position value loss that triggers a stop-loss exit.
_DEFAULT_STOP_LOSS_PCT: float = 0.05  # 5 %

# Fraction of position value gain that triggers a take-profit exit.
_DEFAULT_TAKE_PROFIT_PCT: float = 0.20  # 20 %

# Maximum seconds a position may be held before an age-based exit is recommended.
_DEFAULT_MAX_HOLD_SECONDS: float = 86_400.0  # 24 hours

# Partial exit fraction — used for take-profit when configured partial exits.
_PARTIAL_EXIT_PCT: float = 0.5


# ---------------------------------------------------------------------------
# PositionMonitor
# ---------------------------------------------------------------------------


class PositionMonitor:
    """Evaluates open positions and recommends exit actions.

    Each call to :meth:`check_positions` fetches current positions via the
    SDK and evaluates them against configured thresholds.  Results are
    :class:`~agent.models.ecosystem.PositionAction` objects — the caller
    (typically :class:`~agent.trading.loop.TradingLoop`) decides whether to
    act on them.

    :meth:`execute_exits` converts non-hold actions into real orders via the
    :class:`~agent.trading.execution.TradeExecutor`.  The permission system
    is consulted for every exit before the order is placed.

    Args:
        agent_id: UUID string of the trading agent.
        config: :class:`~agent.config.AgentConfig` with connectivity settings.
        enforcer: :class:`~agent.permissions.enforcement.PermissionEnforcer`
            used to gate every ``close_position`` action.
        executor: :class:`~agent.trading.execution.TradeExecutor` used to
            submit exit orders.
        sdk_client: SDK client for fetching open positions.  When ``None``
            :meth:`check_positions` returns an empty list.
        stop_loss_pct: Override for the stop-loss percentage trigger.
            Defaults to :data:`_DEFAULT_STOP_LOSS_PCT`.
        take_profit_pct: Override for the take-profit percentage trigger.
            Defaults to :data:`_DEFAULT_TAKE_PROFIT_PCT`.
        max_hold_seconds: Override for the maximum holding duration in seconds.
            Defaults to :data:`_DEFAULT_MAX_HOLD_SECONDS`.

    Example::

        monitor = PositionMonitor(
            agent_id="550e8400-...",
            config=config,
            enforcer=enforcer,
            executor=executor,
            sdk_client=sdk,
        )
        actions = await monitor.check_positions("550e8400-...")
        exit_actions = [a for a in actions if a.action != "hold"]
        if exit_actions:
            results = await monitor.execute_exits(exit_actions)
    """

    def __init__(
        self,
        agent_id: str,
        config: AgentConfig,
        enforcer: PermissionEnforcer,
        executor: TradeExecutor,
        sdk_client: Any = None,  # noqa: ANN401
        stop_loss_pct: float = _DEFAULT_STOP_LOSS_PCT,
        take_profit_pct: float = _DEFAULT_TAKE_PROFIT_PCT,
        max_hold_seconds: float = _DEFAULT_MAX_HOLD_SECONDS,
    ) -> None:
        self._agent_id = agent_id
        self._config = config
        self._enforcer = enforcer
        self._executor = executor
        self._sdk_client: Any = sdk_client
        self._stop_loss_pct = stop_loss_pct
        self._take_profit_pct = take_profit_pct
        self._max_hold_seconds = max_hold_seconds

        self._log = logger.bind(agent_id=agent_id, component="position_monitor")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_positions(self, agent_id: str) -> list[PositionAction]:
        """Evaluate all open positions and return recommended actions.

        Fetches the current open positions via the SDK and for each one:

        1. Computes the current unrealised P&L.
        2. Checks whether the stop-loss threshold has been breached
           (``unrealized_pnl_pct < -stop_loss_pct``).
        3. Checks whether the take-profit threshold has been reached
           (``unrealized_pnl_pct >= take_profit_pct``).
        4. Checks whether the position has been held longer than
           ``max_hold_seconds``.

        Stop-loss exits take priority over take-profit exits.  Age-based
        exits are the lowest priority (only triggered when neither SL nor
        TP conditions apply).

        Args:
            agent_id: UUID string of the agent whose positions to evaluate.
                This is used for logging context; the SDK client already
                has the agent's API key embedded.

        Returns:
            A list of :class:`~agent.models.ecosystem.PositionAction`
            objects, one per open position.  Returns an empty list when
            no positions are open or the SDK is unavailable.
        """
        if self._sdk_client is None:
            self._log.debug("position_monitor.check.no_sdk_client")
            return []

        # ── Fetch open positions ─────────────────────────────────────────
        positions = await self._fetch_positions()
        if not positions:
            self._log.debug(
                "position_monitor.check.no_positions",
                agent_id=agent_id,
            )
            return []

        actions: list[PositionAction] = []
        now = datetime.now(UTC)

        for pos in positions:
            action = self._evaluate_position(pos, now)
            actions.append(action)

        non_hold = [a for a in actions if a.action != "hold"]
        self._log.info(
            "position_monitor.check.complete",
            agent_id=agent_id,
            total_positions=len(positions),
            exit_actions=len(non_hold),
        )
        return actions

    async def execute_exits(
        self,
        actions: list[PositionAction],
    ) -> list[ExecutionResult]:
        """Execute exit orders for all non-hold :class:`~agent.models.ecosystem.PositionAction` objects.

        For each action with ``action != "hold"``:

        1. Check permission via the enforcer (``close_position`` action).
        2. Determine the exit side (opposite of the assumed long position: ``"sell"``).
        3. Build a synthetic :class:`~agent.models.ecosystem.TradeDecision`
           and delegate to :class:`~agent.trading.execution.TradeExecutor`.

        Only ``full_exit`` and ``partial_exit`` actions produce orders.
        ``hold`` actions are silently skipped.

        Args:
            actions: List of :class:`~agent.models.ecosystem.PositionAction`
                objects from :meth:`check_positions`.

        Returns:
            List of :class:`~agent.models.ecosystem.ExecutionResult` objects,
            one per executed exit.  ``hold`` actions are excluded from the
            result list.
        """
        exit_actions = [a for a in actions if a.action != "hold"]
        if not exit_actions:
            return []

        results: list[ExecutionResult] = []

        for action in exit_actions:
            # ── Permission check ─────────────────────────────────────────
            try:
                enforcement = await self._enforcer.check_action(
                    self._agent_id,
                    "close_position",
                    {"symbol": action.symbol, "value": str(abs(action.current_pnl))},
                )
            except Exception as exc:  # noqa: BLE001
                self._log.error(
                    "position_monitor.exit.permission_error",
                    symbol=action.symbol,
                    error=str(exc),
                )
                continue  # Skip this exit rather than crashing the batch.

            if not enforcement.allowed:
                self._log.info(
                    "position_monitor.exit.permission_denied",
                    symbol=action.symbol,
                    reason=enforcement.reason,
                )
                continue

            # ── Build a synthetic TradeDecision for the exit ─────────────
            # Exits are always sells (closing a long position) in this
            # simplified model.  Future work: track position direction
            # explicitly for short support.
            exit_qty_pct = Decimal(str(action.exit_pct)) * Decimal("0.10")
            # Clamp to valid TradeDecision bounds.
            exit_qty_pct = min(Decimal("0.10"), max(Decimal("0.001"), exit_qty_pct))

            exit_decision = TradeDecision(
                symbol=action.symbol,
                action="sell",
                quantity_pct=exit_qty_pct,
                confidence=0.9,  # Exit decisions are high-confidence by construction.
                reasoning=(
                    f"Position monitor exit: {action.reason}. "
                    f"Current PnL: {action.current_pnl}. "
                    f"Urgency: {action.urgency}."
                ),
                signals={"exit_trigger": action.reason, "urgency": action.urgency},
                risk_notes=f"Automated exit triggered by monitor (urgency={action.urgency}).",
                strategy_weights={},
            )

            self._log.info(
                "position_monitor.exit.executing",
                symbol=action.symbol,
                action=action.action,
                exit_pct=action.exit_pct,
                urgency=action.urgency,
                reason=action.reason,
            )

            result = await self._executor.execute(exit_decision)
            results.append(result)

            if result.success:
                self._log.info(
                    "position_monitor.exit.success",
                    symbol=action.symbol,
                    order_id=result.order_id,
                    fill_price=str(result.fill_price) if result.fill_price else None,
                )
            else:
                self._log.error(
                    "position_monitor.exit.failed",
                    symbol=action.symbol,
                    error=result.error_message,
                )

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_positions(self) -> list[dict[str, Any]]:
        """Fetch open positions from the SDK.

        Returns:
            List of raw position dicts from the SDK.  Each dict should have
            at minimum ``symbol``, ``unrealized_pnl``, ``unrealized_pnl_pct``,
            and ``opened_at`` keys.  Returns an empty list on failure.
        """
        try:
            raw = await self._sdk_client.get_positions()
            if isinstance(raw, list):
                return raw
            if isinstance(raw, dict) and "error" in raw:
                self._log.warning(
                    "position_monitor.fetch_positions.sdk_error",
                    error=raw.get("error"),
                )
                return []
            return []
        except Exception as exc:  # noqa: BLE001
            self._log.warning(
                "position_monitor.fetch_positions.exception",
                error=str(exc),
            )
            return []

    def _evaluate_position(
        self,
        position: dict[str, Any],
        now: datetime,
    ) -> PositionAction:
        """Evaluate a single position dict and return the recommended action.

        Applies stop-loss, take-profit, and age-based exit rules in priority
        order.  Returns a ``"hold"`` action if no threshold is breached.

        Args:
            position: Raw position dict from the SDK.  Expected keys:
                ``symbol`` (str), ``unrealized_pnl`` (str or numeric),
                ``unrealized_pnl_pct`` (str or numeric, as a decimal fraction
                OR percentage — normalised below), ``opened_at`` (ISO-8601 str
                or datetime).
            now: Current UTC datetime (passed in to avoid repeated syscalls
                in batch evaluations).

        Returns:
            A :class:`~agent.models.ecosystem.PositionAction` describing the
            recommended action.
        """
        symbol: str = str(position.get("symbol", "UNKNOWN"))

        # ── Normalise PnL values ─────────────────────────────────────────
        current_pnl = self._parse_decimal(position.get("unrealized_pnl"), Decimal("0"))
        pnl_pct_raw = self._parse_float(position.get("unrealized_pnl_pct"), 0.0)

        # The SDK may return pnl_pct as a fraction (0.05 = 5%) or as a
        # percentage (5.0 = 5%).  Normalise to fraction.
        if abs(pnl_pct_raw) > 1.0:
            pnl_pct = pnl_pct_raw / 100.0
        else:
            pnl_pct = pnl_pct_raw

        # ── Normalise opened_at timestamp ────────────────────────────────
        opened_at: datetime | None = self._parse_datetime(position.get("opened_at"))
        hold_seconds: float = 0.0
        if opened_at is not None:
            delta = now - opened_at
            hold_seconds = delta.total_seconds()

        # ── 1. Stop-loss check ───────────────────────────────────────────
        if pnl_pct < -self._stop_loss_pct:
            return PositionAction(
                symbol=symbol,
                current_pnl=current_pnl,
                action="full_exit",
                exit_pct=1.0,
                reason=(
                    f"Stop-loss breached: PnL {pnl_pct:.2%} < "
                    f"-{self._stop_loss_pct:.2%} threshold."
                ),
                urgency="immediate",
            )

        # ── 2. Take-profit check ─────────────────────────────────────────
        if pnl_pct >= self._take_profit_pct:
            return PositionAction(
                symbol=symbol,
                current_pnl=current_pnl,
                action="full_exit",
                exit_pct=1.0,
                reason=(
                    f"Take-profit reached: PnL {pnl_pct:.2%} >= "
                    f"{self._take_profit_pct:.2%} threshold."
                ),
                urgency="next_cycle",
            )

        # ── 3. Age-based exit ────────────────────────────────────────────
        if hold_seconds > self._max_hold_seconds:
            hours_held = hold_seconds / 3600
            return PositionAction(
                symbol=symbol,
                current_pnl=current_pnl,
                action="full_exit",
                exit_pct=1.0,
                reason=(
                    f"Maximum holding duration exceeded: position held "
                    f"{hours_held:.1f}h (limit "
                    f"{self._max_hold_seconds / 3600:.1f}h)."
                ),
                urgency="next_cycle",
            )

        # ── 4. Hold ──────────────────────────────────────────────────────
        self._log.debug(
            "position_monitor.evaluate.hold",
            symbol=symbol,
            pnl_pct=f"{pnl_pct:.4f}",
            hold_seconds=int(hold_seconds),
        )
        return PositionAction(
            symbol=symbol,
            current_pnl=current_pnl,
            action="hold",
            exit_pct=0.0,
            reason="No exit threshold breached.",
            urgency="monitor",
        )

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_decimal(raw: Any, default: Decimal) -> Decimal:  # noqa: ANN401
        """Coerce a raw value to Decimal, returning ``default`` on failure.

        Args:
            raw: The raw value to coerce (str, int, float, or None).
            default: The fallback value.

        Returns:
            A :class:`~decimal.Decimal`.
        """
        if raw is None:
            return default
        try:
            return Decimal(str(raw))
        except Exception:  # noqa: BLE001
            return default

    @staticmethod
    def _parse_float(raw: Any, default: float) -> float:  # noqa: ANN401
        """Coerce a raw value to float, returning ``default`` on failure.

        Args:
            raw: The raw value to coerce.
            default: The fallback value.

        Returns:
            A ``float``.
        """
        if raw is None:
            return default
        try:
            return float(raw)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_datetime(raw: Any) -> datetime | None:  # noqa: ANN401
        """Parse a raw timestamp to a timezone-aware UTC datetime.

        Accepts ISO-8601 strings and :class:`datetime` objects.

        Args:
            raw: An ISO-8601 string, a ``datetime``, or ``None``.

        Returns:
            A timezone-aware :class:`datetime` in UTC, or ``None`` if
            parsing fails.
        """
        if raw is None:
            return None
        if isinstance(raw, datetime):
            # Ensure timezone-aware.
            if raw.tzinfo is None:
                return raw.replace(tzinfo=UTC)
            return raw
        if isinstance(raw, str):
            try:
                # Python 3.11+ handles "Z" suffix; use replace for 3.9/3.10 compat.
                normalised = raw.replace("Z", "+00:00")
                dt = datetime.fromisoformat(normalised)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt
            except (ValueError, AttributeError):
                return None
        return None
