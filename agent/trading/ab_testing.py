"""A/B testing framework for running two strategy parameter variants in parallel.

:class:`ABTestRunner` manages the full lifecycle of a strategy A/B test:
creation, round-robin signal allocation, outcome recording, statistical
evaluation, and winner promotion via the platform strategy registry.

Architecture::

    ABTestRunner
        │
        ├── create_test()  → ABTest (stored in _active_tests + persisted to agent_journal)
        │
        ├── record_result() → appends outcome to per-variant deque in _variant_records
        │
        ├── evaluate()     → ABTestResult
        │       │
        │       ├── _compute_variant_performance()  → StrategyPerformance
        │       └── _run_significance_test()        → (p_value, is_significant, winner)
        │
        └── promote_winner() → calls platform strategy registry via REST client

One test per strategy at a time (enforced per agent_id + strategy_name).
Round-robin allocation is implemented with a per-test counter.

Persistence:
    A/B test metadata is stored as an ``agent_journal`` row with
    ``entry_type="insight"`` and the full test state serialised to
    ``market_context`` JSONB.  The DB ``entry_type`` check constraint does not
    include ``"ab_test"`` so ``"insight"`` is used as the closest allowed
    category; the type is identified by ``market_context["ab_test_metadata"]``.

Usage::

    from agent.trading.ab_testing import ABTest, ABTestRunner

    runner = ABTestRunner(rest_client=rest, session_factory=session_factory)

    # Create a test comparing two RSI threshold variants
    test = await runner.create_test(
        agent_id="uuid-string",
        strategy_name="rsi_strategy",
        variant_a_params={"rsi_threshold": 30, "confidence": 0.60},
        variant_b_params={"rsi_threshold": 25, "confidence": 0.65},
        min_trades=50,
    )

    # Record each trade outcome as it comes in
    await runner.record_result(test.id, "a", signal, pnl=Decimal("42.50"))

    # Evaluate once enough trades have accumulated
    result = await runner.evaluate(test.id)
    if result.is_significant and result.winner != "inconclusive":
        await runner.promote_winner(test.id)
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from agent.models.ecosystem import ABTestResult, StrategyPerformance
from agent.trading.signal_generator import TradingSignal

logger = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Statistical significance threshold (conventional 5% level).
# Tests with p_value < _SIGNIFICANCE_ALPHA are considered statistically
# significant, allowing the winner to be declared.
_SIGNIFICANCE_ALPHA: float = 0.05

# Minimum number of completed trades required per variant before the
# statistical test is meaningful.  Callers can override via ``min_trades``
# on :meth:`ABTestRunner.create_test`.
_DEFAULT_MIN_TRADES: int = 50

# Maximum number of trade records retained per variant in memory.
# At 50 min_trades this allows a full window + 20% headroom.
_MAX_RECORDS_PER_VARIANT: int = 200

# Annualisation factor for per-trade Sharpe estimate (proxy: 252 trading days).
_SHARPE_ANNUALISATION: float = 252.0

# Proxy starting balance used for max-drawdown normalisation (platform default).
_PROXY_BALANCE: float = 10_000.0


# ── Data models ────────────────────────────────────────────────────────────────


class ABTest:
    """State object for a single A/B test between two strategy variants.

    Not a frozen Pydantic model because it is mutated incrementally as results
    come in.  ``ABTestRunner`` is the only writer.

    Args:
        id: Unique identifier for this test (UUID string).
        agent_id: Agent that owns this test.
        strategy_name: The strategy under test.
        variant_a: Parameter dict for variant A.
        variant_b: Parameter dict for variant B.
        min_trades: Minimum completed trades per variant before evaluation is
            meaningful and a winner can be declared.
        status: Current test status: ``"active"``, ``"completed"``, or
            ``"cancelled"``.
        winner: Winning variant (``"a"``, ``"b"``, or ``"inconclusive"``).
            ``None`` until :meth:`ABTestRunner.evaluate` is called and both
            variants have reached ``min_trades``.
        started_at: UTC timestamp when the test was created.
        completed_at: UTC timestamp when the test transitioned out of
            ``"active"`` status.  ``None`` while active.
        _round_robin_counter: Internal counter driving round-robin allocation.
    """

    __slots__ = (
        "id",
        "agent_id",
        "strategy_name",
        "variant_a",
        "variant_b",
        "min_trades",
        "status",
        "winner",
        "started_at",
        "completed_at",
        "_round_robin_counter",
    )

    def __init__(
        self,
        *,
        id: str,
        agent_id: str,
        strategy_name: str,
        variant_a: dict[str, Any],
        variant_b: dict[str, Any],
        min_trades: int = _DEFAULT_MIN_TRADES,
        status: str = "active",
        winner: str | None = None,
        started_at: datetime,
        completed_at: datetime | None = None,
    ) -> None:
        self.id = id
        self.agent_id = agent_id
        self.strategy_name = strategy_name
        self.variant_a = variant_a
        self.variant_b = variant_b
        self.min_trades = min_trades
        self.status = status
        self.winner = winner
        self.started_at = started_at
        self.completed_at = completed_at
        self._round_robin_counter: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise the test to a JSON-safe dict for persistence.

        Returns:
            Dict suitable for storing in the ``market_context`` JSONB column.
        """
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "strategy_name": self.strategy_name,
            "variant_a": self.variant_a,
            "variant_b": self.variant_b,
            "min_trades": self.min_trades,
            "status": self.status,
            "winner": self.winner,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "round_robin_counter": self._round_robin_counter,
        }


class _TradeRecord:
    """Lightweight in-memory record of one A/B test trade outcome.

    Args:
        variant: Which variant this trade belongs to: ``"a"`` or ``"b"``.
        signal: The :class:`~agent.trading.signal_generator.TradingSignal`
            that was acted on.
        outcome_pnl: Realised PnL in USDT.  ``None`` while position is open.
        recorded_at: UTC timestamp when the record was created.
    """

    __slots__ = ("variant", "signal", "outcome_pnl", "recorded_at")

    def __init__(
        self,
        variant: str,
        signal: TradingSignal,
        outcome_pnl: Decimal | None,
        recorded_at: datetime,
    ) -> None:
        self.variant = variant
        self.signal = signal
        self.outcome_pnl = outcome_pnl
        self.recorded_at = recorded_at


# ── ABTestRunner ───────────────────────────────────────────────────────────────


class ABTestRunner:
    """Manages A/B tests between two strategy parameter variants.

    Maintains per-test in-memory trade records (bounded deques), drives
    round-robin signal allocation, evaluates statistical significance, and
    promotes the winning variant by calling the platform strategy registry.

    Only one active test per (agent_id, strategy_name) pair is allowed at any
    time.  Attempting to create a second test raises :class:`DuplicateABTestError`.

    Persistence is optional.  When ``session_factory`` is provided, test
    creation and completion events are written to ``agent_journal`` rows.
    When ``None``, the runner operates in a pure in-memory mode (useful for
    tests and scripts).

    The ``rest_client`` is required only for :meth:`promote_winner`, which
    calls the platform strategy registry API.  Passing ``None`` disables
    promotion (the method logs a warning and returns without error).

    Args:
        rest_client: An ``httpx.AsyncClient`` pointed at the platform REST API
            (base URL already set).  Used by :meth:`promote_winner` to push
            the winning variant's parameters.  ``None`` disables promotion.
        session_factory: Optional async callable returning an open
            ``AsyncSession``.  Enables persisting test state to
            ``agent_journal``.  ``None`` disables all DB writes.

    Example::

        runner = ABTestRunner(rest_client=http_client, session_factory=factory)

        test = await runner.create_test(
            agent_id="agent-uuid",
            strategy_name="momentum_strategy",
            variant_a_params={"rsi_low": 30, "position_size_pct": 0.05},
            variant_b_params={"rsi_low": 25, "position_size_pct": 0.04},
            min_trades=50,
        )

        # In the trading loop — allocate signal to the next variant
        variant = runner.next_variant(test.id)   # "a" or "b"
        await runner.record_result(test.id, variant, signal, outcome_pnl=pnl)

        result = await runner.evaluate(test.id)
        if result.is_significant:
            await runner.promote_winner(test.id)
    """

    def __init__(
        self,
        *,
        rest_client: Any = None,  # noqa: ANN401  # httpx.AsyncClient
        session_factory: Any = None,  # noqa: ANN401  # async_sessionmaker
    ) -> None:
        self._rest = rest_client
        self._session_factory = session_factory

        # _tests[test_id] → ABTest
        self._tests: dict[str, ABTest] = {}

        # _active_index[agent_id][strategy_name] → test_id
        # Used to enforce one-test-per-strategy and to look up tests by name.
        self._active_index: dict[str, dict[str, str]] = defaultdict(dict)

        # _records[test_id]["a" | "b"] → deque[_TradeRecord]
        self._records: dict[str, dict[str, deque[_TradeRecord]]] = {}

        self._log = logger.bind(component="ab_test_runner")

    # ── Public API ─────────────────────────────────────────────────────────────

    async def create_test(
        self,
        agent_id: str,
        strategy_name: str,
        variant_a_params: dict[str, Any],
        variant_b_params: dict[str, Any],
        min_trades: int = _DEFAULT_MIN_TRADES,
    ) -> ABTest:
        """Create a new A/B test for a strategy.

        Validates that no active test already exists for this
        (agent_id, strategy_name) pair.  Creates the :class:`ABTest` state
        object, initialises in-memory record deques, and optionally persists
        the test metadata to ``agent_journal``.

        Args:
            agent_id: UUID string of the agent owning the test.
            strategy_name: Name of the strategy under test.
            variant_a_params: Parameter overrides for variant A.
            variant_b_params: Parameter overrides for variant B.
            min_trades: Minimum completed trades per variant required before
                a winner can be declared.  Default: 50.

        Returns:
            The newly created :class:`ABTest` instance.

        Raises:
            DuplicateABTestError: If an active test already exists for this
                strategy.
            ValueError: If ``min_trades`` is less than 1.
        """
        if min_trades < 1:
            raise ValueError(f"min_trades must be >= 1, got {min_trades}.")

        # Enforce one-test-per-strategy constraint.
        existing_id = self._active_index.get(agent_id, {}).get(strategy_name)
        if existing_id is not None:
            existing = self._tests.get(existing_id)
            if existing is not None and existing.status == "active":
                raise DuplicateABTestError(
                    f"Active A/B test already exists for strategy {strategy_name!r} "
                    f"(agent {agent_id!r}, test_id={existing_id!r}). "
                    "Cancel it before creating a new one."
                )

        test_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        test = ABTest(
            id=test_id,
            agent_id=agent_id,
            strategy_name=strategy_name,
            variant_a=dict(variant_a_params),
            variant_b=dict(variant_b_params),
            min_trades=min_trades,
            status="active",
            winner=None,
            started_at=now,
            completed_at=None,
        )

        self._tests[test_id] = test
        self._active_index[agent_id][strategy_name] = test_id
        self._records[test_id] = {
            "a": deque(maxlen=_MAX_RECORDS_PER_VARIANT),
            "b": deque(maxlen=_MAX_RECORDS_PER_VARIANT),
        }

        self._log.info(
            "agent.trade.ab_test.created",
            test_id=test_id,
            agent_id=agent_id,
            strategy=strategy_name,
            min_trades=min_trades,
        )

        await self._persist_test_event(test, event="created")
        return test

    def next_variant(self, test_id: str) -> str:
        """Return the next variant for round-robin signal allocation.

        Alternates between ``"a"`` and ``"b"`` using a per-test counter so
        that both variants receive an equal number of signals.  The counter
        advances atomically (no concurrency concerns — ABTestRunner is not
        thread-safe by design, consistent with the rest of the agent layer).

        Args:
            test_id: The test identifier returned by :meth:`create_test`.

        Returns:
            ``"a"`` or ``"b"``.

        Raises:
            ABTestNotFoundError: If ``test_id`` does not exist.
            ABTestInactiveError: If the test is not in ``"active"`` status.
        """
        test = self._get_active_test(test_id)
        variant = "a" if test._round_robin_counter % 2 == 0 else "b"
        test._round_robin_counter += 1
        return variant

    async def record_result(
        self,
        test_id: str,
        variant: str,
        signal: TradingSignal,
        outcome_pnl: Decimal | None = None,
    ) -> None:
        """Append a trade outcome to the rolling record for a variant.

        Call once when the signal is generated (``outcome_pnl=None``) and
        again when the position closes (``outcome_pnl=<realised PnL>``).

        Only the most recent :data:`_MAX_RECORDS_PER_VARIANT` records are
        kept in memory (bounded deque).

        Args:
            test_id: The test identifier.
            variant: Which variant the trade belongs to: ``"a"`` or ``"b"``.
            signal: The :class:`~agent.trading.signal_generator.TradingSignal`
                that generated the trade.
            outcome_pnl: Realised PnL in USDT.  ``None`` while position open.

        Raises:
            ABTestNotFoundError: If ``test_id`` does not exist.
            ABTestInactiveError: If the test is no longer active.
            ValueError: If ``variant`` is not ``"a"`` or ``"b"``.
        """
        if variant not in ("a", "b"):
            raise ValueError(f"variant must be 'a' or 'b', got {variant!r}.")

        test = self._get_active_test(test_id)
        record = _TradeRecord(
            variant=variant,
            signal=signal,
            outcome_pnl=outcome_pnl,
            recorded_at=datetime.now(UTC),
        )
        self._records[test_id][variant].append(record)

        completed_a = _count_completed(self._records[test_id]["a"])
        completed_b = _count_completed(self._records[test_id]["b"])

        self._log.debug(
            "agent.trade.ab_test.record",
            test_id=test_id,
            strategy=test.strategy_name,
            variant=variant,
            pnl=str(outcome_pnl) if outcome_pnl is not None else "open",
            completed_a=completed_a,
            completed_b=completed_b,
            needed=test.min_trades,
        )

    async def evaluate(self, test_id: str) -> ABTestResult:
        """Evaluate the A/B test and return statistical results.

        Computes :class:`~agent.models.ecosystem.StrategyPerformance` metrics
        for both variants, then runs a two-sample t-test on their PnL
        distributions to assess statistical significance.

        A winner is only declared when:
        1. Both variants have at least ``min_trades`` completed trades.
        2. The t-test p-value is below :data:`_SIGNIFICANCE_ALPHA`.

        If either condition is not met, ``winner`` is ``"inconclusive"``.

        Args:
            test_id: The test identifier.

        Returns:
            An :class:`~agent.models.ecosystem.ABTestResult` with full
            evaluation results.

        Raises:
            ABTestNotFoundError: If ``test_id`` does not exist.
            InsufficientDataError: If neither variant has reached
                ``min_trades`` completed trades yet.
        """
        test = self._get_test(test_id)
        records_a = self._records.get(test_id, {}).get("a", deque())
        records_b = self._records.get(test_id, {}).get("b", deque())

        completed_a = _count_completed(records_a)
        completed_b = _count_completed(records_b)

        if completed_a < test.min_trades and completed_b < test.min_trades:
            raise InsufficientDataError(
                f"A/B test {test_id!r} needs {test.min_trades} completed trades per variant. "
                f"Current: variant_a={completed_a}, variant_b={completed_b}."
            )

        perf_a = _compute_variant_performance(records_a, strategy_name=f"{test.strategy_name}_a")
        perf_b = _compute_variant_performance(records_b, strategy_name=f"{test.strategy_name}_b")

        pnl_a = _extract_completed_pnls(records_a)
        pnl_b = _extract_completed_pnls(records_b)

        p_value, is_significant, winner = _run_significance_test(
            pnl_a,
            pnl_b,
            min_trades=test.min_trades,
            alpha=_SIGNIFICANCE_ALPHA,
        )

        recommendation = _build_recommendation(
            test=test,
            perf_a=perf_a,
            perf_b=perf_b,
            winner=winner,
            p_value=p_value,
            is_significant=is_significant,
            completed_a=completed_a,
            completed_b=completed_b,
        )

        self._log.info(
            "agent.trade.ab_test.evaluated",
            test_id=test_id,
            strategy=test.strategy_name,
            winner=winner,
            p_value=round(p_value, 4),
            is_significant=is_significant,
            completed_a=completed_a,
            completed_b=completed_b,
        )

        return ABTestResult(
            test_id=test_id,
            strategy_name=test.strategy_name,
            variant_a_performance=perf_a,
            variant_b_performance=perf_b,
            winner=winner,
            p_value=p_value,
            is_significant=is_significant,
            recommendation=recommendation,
            evaluated_at=datetime.now(UTC),
        )

    async def promote_winner(self, test_id: str) -> None:
        """Promote the winning variant's parameters to the strategy registry.

        Marks the test as ``"completed"``, persists the final state, then
        (if a REST client is available) calls the strategy registry API to
        create a new strategy version with the winning parameters.

        If the test has not yet been evaluated or the winner is
        ``"inconclusive"``, the method logs a warning and returns without
        taking action.  It does not raise in these cases to allow the caller
        to safely call this method after ``evaluate()`` in all cases.

        Args:
            test_id: The test identifier.

        Raises:
            ABTestNotFoundError: If ``test_id`` does not exist.
        """
        test = self._get_test(test_id)

        if test.winner is None:
            self._log.warning(
                "agent.trade.ab_test.promote.not_evaluated",
                test_id=test_id,
                strategy=test.strategy_name,
                reason="Call evaluate() before promote_winner().",
            )
            return

        if test.winner == "inconclusive":
            self._log.warning(
                "agent.trade.ab_test.promote.inconclusive",
                test_id=test_id,
                strategy=test.strategy_name,
                reason="No statistically significant winner; not promoting.",
            )
            return

        winning_params = test.variant_a if test.winner == "a" else test.variant_b

        # Mark test complete.
        test.status = "completed"
        test.completed_at = datetime.now(UTC)

        # Remove from active index so a new test for this strategy can be created.
        self._active_index.get(test.agent_id, {}).pop(test.strategy_name, None)

        self._log.info(
            "agent.trade.ab_test.promoting_winner",
            test_id=test_id,
            strategy=test.strategy_name,
            winner=test.winner,
            winning_params=winning_params,
        )

        # Push winning parameters to the strategy registry via REST.
        await self._push_winning_params(test, winning_params)

        # Persist completion event.
        await self._persist_test_event(test, event="completed")

    async def cancel_test(self, test_id: str) -> None:
        """Cancel an active A/B test.

        Marks the test as ``"cancelled"``, removes it from the active index,
        and persists the cancellation event.  Records accumulated so far are
        retained in memory until the runner is garbage-collected.

        Args:
            test_id: The test identifier.

        Raises:
            ABTestNotFoundError: If ``test_id`` does not exist.
            ABTestInactiveError: If the test is already completed or cancelled.
        """
        test = self._get_active_test(test_id)
        test.status = "cancelled"
        test.completed_at = datetime.now(UTC)

        self._active_index.get(test.agent_id, {}).pop(test.strategy_name, None)

        self._log.info(
            "agent.trade.ab_test.cancelled",
            test_id=test_id,
            strategy=test.strategy_name,
        )

        await self._persist_test_event(test, event="cancelled")

    async def get_active_tests(self, agent_id: str) -> list[ABTest]:
        """Return all active A/B tests for an agent.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            A list of :class:`ABTest` instances with ``status="active"``,
            ordered by ``started_at`` ascending.  Empty when no active tests
            exist for this agent.
        """
        active_ids = self._active_index.get(agent_id, {}).values()
        tests = [
            self._tests[tid]
            for tid in active_ids
            if tid in self._tests and self._tests[tid].status == "active"
        ]
        return sorted(tests, key=lambda t: t.started_at)

    def get_test(self, test_id: str) -> ABTest:
        """Return a test by ID (active or completed).

        Args:
            test_id: The test identifier.

        Returns:
            The :class:`ABTest` instance.

        Raises:
            ABTestNotFoundError: If ``test_id`` does not exist.
        """
        return self._get_test(test_id)

    def variant_trade_counts(self, test_id: str) -> dict[str, int]:
        """Return the number of completed trades per variant.

        Useful for checking progress toward ``min_trades`` before calling
        :meth:`evaluate`.

        Args:
            test_id: The test identifier.

        Returns:
            Dict with keys ``"a"`` and ``"b"`` mapping to completed trade
            counts.  Returns zeros if the test does not exist.
        """
        records = self._records.get(test_id, {})
        return {
            "a": _count_completed(records.get("a", deque())),
            "b": _count_completed(records.get("b", deque())),
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_test(self, test_id: str) -> ABTest:
        """Look up a test by ID; raise :class:`ABTestNotFoundError` if missing."""
        test = self._tests.get(test_id)
        if test is None:
            raise ABTestNotFoundError(
                f"A/B test {test_id!r} not found.",
                test_id=test_id,
            )
        return test

    def _get_active_test(self, test_id: str) -> ABTest:
        """Look up an active test; raise if missing or inactive."""
        test = self._get_test(test_id)
        if test.status != "active":
            raise ABTestInactiveError(
                f"A/B test {test_id!r} is not active (status={test.status!r}).",
                test_id=test_id,
            )
        return test

    async def _push_winning_params(
        self,
        test: ABTest,
        winning_params: dict[str, Any],
    ) -> None:
        """Call the strategy registry API to create a new version with winning params.

        Silently skips if no REST client is configured.

        Args:
            test: The completed :class:`ABTest`.
            winning_params: Parameter overrides from the winning variant.
        """
        if self._rest is None:
            self._log.warning(
                "agent.trade.ab_test.promote.no_rest_client",
                test_id=test.id,
                strategy=test.strategy_name,
                reason="No REST client configured; skipping parameter promotion.",
            )
            return

        try:
            # Search for the strategy by name to get its ID.
            resp = await self._rest.get(
                "/api/v1/strategies",
                params={"search": test.strategy_name, "limit": 10},
            )
            resp.raise_for_status()
            body = resp.json()
            strategies = body.get("strategies", body) if isinstance(body, dict) else body

            strategy_id: str | None = None
            for s in strategies:
                if s.get("name") == test.strategy_name:
                    strategy_id = str(s["id"])
                    break

            if strategy_id is None:
                self._log.warning(
                    "agent.trade.ab_test.promote.strategy_not_found",
                    test_id=test.id,
                    strategy=test.strategy_name,
                    reason="Strategy not found in registry; cannot create new version.",
                )
                return

            # Create a new immutable version with the winning parameters.
            version_resp = await self._rest.post(
                f"/api/v1/strategies/{strategy_id}/versions",
                json={
                    "definition": winning_params,
                    "notes": (
                        f"A/B test {test.id[:8]} winner (variant_{test.winner}). "
                        f"Promoted at {datetime.now(UTC).isoformat()}."
                    ),
                },
            )
            version_resp.raise_for_status()
            new_version = version_resp.json()

            self._log.info(
                "agent.trade.ab_test.promote.success",
                test_id=test.id,
                strategy=test.strategy_name,
                strategy_id=strategy_id,
                new_version=new_version.get("version"),
                winning_variant=test.winner,
            )

        except Exception as exc:  # noqa: BLE001
            # Never let a promotion failure crash the trading loop — log and continue.
            self._log.error(
                "agent.trade.ab_test.promote.error",
                test_id=test.id,
                strategy=test.strategy_name,
                error=str(exc),
            )

    async def _persist_test_event(self, test: ABTest, event: str) -> None:
        """Write a journal entry capturing the test state.

        Stores A/B test metadata as ``entry_type="insight"`` in ``agent_journal``
        with the full test state serialised to ``market_context``.  The DB
        ``entry_type`` CHECK constraint only allows the core set; ``"insight"``
        is the closest allowed category.  Callers can identify A/B test entries
        by ``market_context["ab_test_metadata"]``.

        Silently skips if no ``session_factory`` was provided.

        Args:
            test: The :class:`ABTest` whose state should be persisted.
            event: Label for the event being recorded (``"created"``,
                ``"completed"``, ``"cancelled"``).
        """
        if self._session_factory is None:
            return

        try:
            from src.database.models import AgentJournal  # noqa: PLC0415
            from src.database.repositories.agent_journal_repo import (  # noqa: PLC0415
                AgentJournalRepository,
            )
        except ImportError:
            self._log.warning(
                "agent.trade.ab_test.persist.import_error",
                reason="src package not available; skipping persistence.",
            )
            return

        title = f"A/B test {event}: {test.strategy_name} ({test.id[:8]})"
        content = (
            f"A/B test {event} for strategy {test.strategy_name!r}. "
            f"Test ID: {test.id}. "
            f"Variant A params: {test.variant_a}. "
            f"Variant B params: {test.variant_b}. "
            f"Min trades: {test.min_trades}. "
            f"Status: {test.status}. "
            f"Winner: {test.winner or 'pending'}."
        )

        try:
            from uuid import UUID as _UUID  # noqa: PLC0415

            journal_row = AgentJournal(
                agent_id=_UUID(test.agent_id),
                entry_type="insight",  # closest allowed type; see db constraint
                title=title,
                content=content,
                market_context={
                    "ab_test_metadata": test.to_dict(),
                    "event": event,
                },
                related_decisions=None,
                tags=["ab_test", test.strategy_name, event],
            )
            async with self._session_factory() as session:
                repo = AgentJournalRepository(session)
                await repo.create(journal_row)
                await session.commit()
                self._log.info(
                    "agent.trade.ab_test.persist.success",
                    test_id=test.id,
                    event=event,
                    entry_id=str(journal_row.id),
                )
        except Exception as exc:  # noqa: BLE001
            self._log.error(
                "agent.trade.ab_test.persist.error",
                test_id=test.id,
                event=event,
                error=str(exc),
            )


# ── Exceptions ─────────────────────────────────────────────────────────────────


class ABTestError(Exception):
    """Base exception for all A/B testing errors.

    All A/B test-specific exceptions inherit from this class so callers can
    use a single ``except ABTestError`` to catch any framework error.
    """


class ABTestNotFoundError(ABTestError):
    """Raised when an A/B test cannot be found by ID.

    Args:
        message: Human-readable error description.
        test_id: The test ID that was not found.
    """

    def __init__(self, message: str = "A/B test not found.", *, test_id: str = "") -> None:
        self.test_id = test_id
        super().__init__(message)


class ABTestInactiveError(ABTestError):
    """Raised when an operation requires an active test but the test is not active.

    Args:
        message: Human-readable error description.
        test_id: The test ID.
    """

    def __init__(self, message: str = "A/B test is not active.", *, test_id: str = "") -> None:
        self.test_id = test_id
        super().__init__(message)


class DuplicateABTestError(ABTestError):
    """Raised when attempting to create a second active test for the same strategy.

    Args:
        message: Human-readable error description.
    """


class InsufficientDataError(ABTestError):
    """Raised when evaluate() is called before min_trades are reached.

    Args:
        message: Human-readable error description including current counts.
    """


# ── Pure statistical helpers ───────────────────────────────────────────────────


def _count_completed(records: deque[_TradeRecord]) -> int:
    """Count records with a non-None ``outcome_pnl`` (closed positions).

    Args:
        records: Deque of :class:`_TradeRecord` instances.

    Returns:
        Number of completed (closed) trade records.
    """
    return sum(1 for r in records if r.outcome_pnl is not None)


def _extract_completed_pnls(records: deque[_TradeRecord]) -> list[float]:
    """Extract completed PnL values from a record deque.

    Args:
        records: Deque of :class:`_TradeRecord` instances.

    Returns:
        List of realised PnL values (floats) for completed trades.
    """
    return [float(r.outcome_pnl) for r in records if r.outcome_pnl is not None]


def _compute_variant_performance(
    records: deque[_TradeRecord],
    *,
    strategy_name: str,
) -> StrategyPerformance:
    """Compute :class:`~agent.models.ecosystem.StrategyPerformance` for one variant.

    All metric computations are copied from the ``_compute_metrics`` pattern
    in ``strategy_manager.py`` for consistency across the monitoring layer.

    Args:
        records: Deque of trade records for this variant.
        strategy_name: Name to assign to the returned StrategyPerformance.

    Returns:
        A :class:`~agent.models.ecosystem.StrategyPerformance` instance.
    """
    total_signals = len(records)
    trades_taken = sum(1 for r in records if r.signal.action != "hold")
    completed_pnls = [r.outcome_pnl for r in records if r.outcome_pnl is not None]
    completed_count = len(completed_pnls)

    if completed_count == 0:
        return StrategyPerformance(
            strategy_name=strategy_name,
            period="weekly",
            total_signals=total_signals,
            trades_taken=trades_taken,
            win_rate=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            total_pnl=Decimal("0"),
            avg_pnl_per_trade=Decimal("0"),
            consecutive_losses=0,
        )

    winners = sum(1 for p in completed_pnls if p > Decimal("0"))
    win_rate = winners / completed_count
    total_pnl = sum(completed_pnls, Decimal("0"))
    avg_pnl = total_pnl / completed_count

    pnl_floats = [float(p) for p in completed_pnls]
    sharpe = _compute_sharpe(pnl_floats, annualisation_factor=_SHARPE_ANNUALISATION)
    max_dd = _compute_max_drawdown(pnl_floats, starting_balance=_PROXY_BALANCE)
    consec = _compute_trailing_consecutive_losses(records)

    return StrategyPerformance(
        strategy_name=strategy_name,
        period="weekly",
        total_signals=total_signals,
        trades_taken=trades_taken,
        win_rate=win_rate,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        total_pnl=total_pnl,
        avg_pnl_per_trade=avg_pnl,
        consecutive_losses=consec,
    )


def _run_significance_test(
    pnl_a: list[float],
    pnl_b: list[float],
    *,
    min_trades: int,
    alpha: float = _SIGNIFICANCE_ALPHA,
) -> tuple[float, bool, str]:
    """Compare two PnL distributions using a two-sample t-test.

    Attempts to import ``scipy.stats.ttest_ind`` for the most accurate result.
    Falls back to Welch's t-test implemented in pure Python when scipy is not
    available.

    A winner is declared only when:
    1. Both variants have at least ``min_trades`` completed trades.
    2. The p-value is below ``alpha``.

    If either condition is not met, ``winner`` is ``"inconclusive"``.

    Args:
        pnl_a: Completed PnL values for variant A.
        pnl_b: Completed PnL values for variant B.
        min_trades: Minimum trades per variant to declare a winner.
        alpha: Significance level threshold.  Default: 0.05.

    Returns:
        A 3-tuple of ``(p_value, is_significant, winner)`` where ``winner``
        is ``"a"``, ``"b"``, or ``"inconclusive"``.
    """
    n_a, n_b = len(pnl_a), len(pnl_b)

    # Both variants must have reached min_trades before we can declare a winner.
    both_ready = (n_a >= min_trades) and (n_b >= min_trades)

    # Need at least 2 samples per group to compute a t-statistic.
    if n_a < 2 or n_b < 2:
        return 1.0, False, "inconclusive"

    p_value = _welch_ttest_p_value(pnl_a, pnl_b)
    is_significant = p_value < alpha and both_ready

    if not is_significant:
        return p_value, False, "inconclusive"

    mean_a = sum(pnl_a) / n_a
    mean_b = sum(pnl_b) / n_b
    winner = "a" if mean_a >= mean_b else "b"

    return p_value, True, winner


def _welch_ttest_p_value(x: list[float], y: list[float]) -> float:
    """Compute a two-tailed Welch's t-test p-value.

    First tries to import ``scipy.stats.ttest_ind`` for accuracy.  Falls
    back to a pure-Python Welch's t-test if scipy is unavailable, using
    the incomplete beta function approximation from the Numerical Recipes
    method.

    The implementation uses the regularised incomplete beta function
    (computed via a continued-fraction expansion) to approximate the
    p-value from the t-statistic and degrees of freedom.

    Args:
        x: First sample.
        y: Second sample.

    Returns:
        Two-tailed p-value in ``[0.0, 1.0]``.  Returns ``1.0`` on any
        numerical error (conservative — does not declare significance).
    """
    try:
        from scipy.stats import ttest_ind  # noqa: PLC0415

        result = ttest_ind(x, y, equal_var=False)
        return float(result.pvalue)
    except ImportError:
        pass
    except Exception:  # noqa: BLE001
        return 1.0

    # Pure Python Welch's t-test fallback.
    return _pure_python_welch_ttest(x, y)


def _pure_python_welch_ttest(x: list[float], y: list[float]) -> float:
    """Pure-Python two-tailed Welch's t-test.

    Uses Welch's approximation for degrees of freedom (Satterthwaite) and
    approximates the p-value via a continued-fraction expansion of the
    regularised incomplete beta function.

    Args:
        x: First sample (length >= 2).
        y: Second sample (length >= 2).

    Returns:
        Two-tailed p-value.  Returns ``1.0`` on numerical errors.
    """
    try:
        n1, n2 = len(x), len(y)
        mean1 = sum(x) / n1
        mean2 = sum(y) / n2
        var1 = sum((v - mean1) ** 2 for v in x) / (n1 - 1)
        var2 = sum((v - mean2) ** 2 for v in y) / (n2 - 1)

        s1 = var1 / n1
        s2 = var2 / n2
        se = s1 + s2

        if se == 0.0:
            return 1.0

        t_stat = (mean1 - mean2) / math.sqrt(se)

        # Welch–Satterthwaite degrees of freedom.
        df = se ** 2 / ((s1 ** 2 / (n1 - 1)) + (s2 ** 2 / (n2 - 1)))

        # Two-tailed p-value via the regularised incomplete beta function.
        x_val = df / (df + t_stat ** 2)
        p_value = _incomplete_beta(x_val, df / 2.0, 0.5)
        return float(max(0.0, min(1.0, p_value)))
    except Exception:  # noqa: BLE001
        return 1.0


def _incomplete_beta(x: float, a: float, b: float) -> float:
    """Regularised incomplete beta function I_x(a, b) via continued fractions.

    This is the standard Numerical Recipes method (betacf) used to compute
    the two-tailed t-test p-value from the t-statistic and degrees of freedom.

    Args:
        x: Upper integration limit in ``[0, 1]``.
        a: Shape parameter (> 0).
        b: Shape parameter (> 0).

    Returns:
        Approximated value of I_x(a, b) in ``[0.0, 1.0]``.
    """
    if x < 0.0 or x > 1.0:
        return 1.0
    if x == 0.0:
        return 0.0
    if x == 1.0:
        return 1.0

    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - lbeta)

    # Use the symmetry relation when x > (a+1)/(a+b+2) for better convergence.
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _incomplete_beta(1.0 - x, b, a)

    # Lentz continued-fraction expansion.
    eps = 3.0e-7
    fp_min = 1.0e-30
    max_iter = 200

    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fp_min:
        d = fp_min
    d = 1.0 / d
    h = d

    for m in range(1, max_iter + 1):
        m2 = 2 * m

        # Even step.
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        c = 1.0 + aa / c
        if abs(d) < fp_min:
            d = fp_min
        if abs(c) < fp_min:
            c = fp_min
        d = 1.0 / d
        h *= d * c

        # Odd step.
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        c = 1.0 + aa / c
        if abs(d) < fp_min:
            d = fp_min
        if abs(c) < fp_min:
            c = fp_min
        d = 1.0 / d
        delta = d * c
        h *= delta

        if abs(delta - 1.0) < eps:
            break

    return front * h / a


def _compute_sharpe(
    pnl_series: list[float],
    *,
    annualisation_factor: float = _SHARPE_ANNUALISATION,
) -> float:
    """Estimate annualised Sharpe ratio from per-trade PnL series.

    Args:
        pnl_series: Per-trade realised PnL values.
        annualisation_factor: Trades per year for annualisation.

    Returns:
        Annualised Sharpe ratio, or ``0.0`` when not computable.
    """
    n = len(pnl_series)
    if n < 2:
        return 0.0
    mean_pnl = sum(pnl_series) / n
    variance = sum((v - mean_pnl) ** 2 for v in pnl_series) / (n - 1)
    std_pnl = math.sqrt(variance)
    if std_pnl == 0.0:
        return 0.0
    return mean_pnl / std_pnl * math.sqrt(annualisation_factor)


def _compute_max_drawdown(
    pnl_series: list[float],
    *,
    starting_balance: float = _PROXY_BALANCE,
) -> float:
    """Compute maximum peak-to-trough equity drawdown fraction.

    Args:
        pnl_series: Chronologically ordered per-trade PnL values.
        starting_balance: Starting equity for normalisation.

    Returns:
        Maximum drawdown as a fraction in ``[0.0, 1.0]``.
    """
    if len(pnl_series) < 2:
        return 0.0
    equity = starting_balance
    peak = equity
    max_dd = 0.0
    for pnl in pnl_series:
        equity += pnl
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 1.0
        if dd > max_dd:
            max_dd = dd
    return min(max_dd, 1.0)


def _compute_trailing_consecutive_losses(records: deque[_TradeRecord]) -> int:
    """Count the trailing streak of consecutive losing closed trades.

    Open positions (``outcome_pnl is None``) are skipped.

    Args:
        records: Rolling deque of :class:`_TradeRecord` instances.

    Returns:
        Number of consecutive losing closed trades at the end of the deque.
    """
    streak = 0
    for record in reversed(records):
        if record.outcome_pnl is None:
            continue
        if record.outcome_pnl <= Decimal("0"):
            streak += 1
        else:
            break
    return streak


def _build_recommendation(
    *,
    test: ABTest,
    perf_a: StrategyPerformance,
    perf_b: StrategyPerformance,
    winner: str,
    p_value: float,
    is_significant: bool,
    completed_a: int,
    completed_b: int,
) -> str:
    """Build a human-readable recommendation string for the A/B test result.

    Args:
        test: The :class:`ABTest` being evaluated.
        perf_a: Performance metrics for variant A.
        perf_b: Performance metrics for variant B.
        winner: Declared winner: ``"a"``, ``"b"``, or ``"inconclusive"``.
        p_value: Computed p-value.
        is_significant: Whether the result is statistically significant.
        completed_a: Completed trade count for variant A.
        completed_b: Completed trade count for variant B.

    Returns:
        Recommendation string.
    """
    lines: list[str] = [
        f"Strategy: {test.strategy_name!r}. "
        f"Variant A: {completed_a} trades, Sharpe={perf_a.sharpe_ratio:.2f}, "
        f"win_rate={perf_a.win_rate:.1%}. "
        f"Variant B: {completed_b} trades, Sharpe={perf_b.sharpe_ratio:.2f}, "
        f"win_rate={perf_b.win_rate:.1%}."
    ]

    if not is_significant:
        if completed_a < test.min_trades or completed_b < test.min_trades:
            missing_a = max(0, test.min_trades - completed_a)
            missing_b = max(0, test.min_trades - completed_b)
            lines.append(
                f"Insufficient data: need {test.min_trades} trades per variant "
                f"(A needs {missing_a} more, B needs {missing_b} more)."
            )
        else:
            lines.append(
                f"Result is not statistically significant (p={p_value:.3f} >= {_SIGNIFICANCE_ALPHA}). "
                "Continue collecting trades before promoting either variant."
            )
    elif winner == "a":
        lines.append(
            f"Variant A wins with p={p_value:.3f}. "
            f"Params: {test.variant_a}. "
            "Call promote_winner() to push these parameters to the strategy registry."
        )
    elif winner == "b":
        lines.append(
            f"Variant B wins with p={p_value:.3f}. "
            f"Params: {test.variant_b}. "
            "Call promote_winner() to push these parameters to the strategy registry."
        )
    else:
        lines.append(
            f"Winner is inconclusive despite p={p_value:.3f}. "
            "Variants may have similar means; no promotion recommended."
        )

    # Also update the winner on the test object for promote_winner() to use.
    test.winner = winner

    return " ".join(lines)
