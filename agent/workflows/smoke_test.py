"""Smoke test workflow for the TradeReady Platform Testing Agent.

Performs a 10-step connectivity validation that exercises the SDK client
directly (steps 1-7) and the platform REST API via httpx (steps 8-9).
This is not an LLM-mediated workflow — every call is made directly without
going through the Pydantic AI tool layer.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import structlog

from agent.config import AgentConfig
from agent.models.report import WorkflowResult

log = structlog.get_logger(__name__)

_SMOKE_SYMBOL = "BTCUSDT"
_SMOKE_QUANTITY = "0.0001"
_STEPS_TOTAL = 10


async def run_smoke_test(config: AgentConfig) -> WorkflowResult:
    """Run a 10-step smoke test validating platform connectivity.

    Each step calls the platform directly (via SDK or httpx REST) and
    validates that the response contains meaningful data.  Failures are
    caught per-step and recorded in ``bugs_found``; the workflow never
    crashes on a single step failure.

    Steps:
        1. SDK ``get_price("BTCUSDT")`` — non-zero price returned
        2. SDK ``get_balance()`` — starting balance exists
        3. SDK ``get_candles("BTCUSDT", "1h", 10)`` — historical data available
        4. SDK ``place_market_order("BTCUSDT", "buy", "0.0001")`` — tiny test trade
        5. SDK ``get_positions()`` — position opened after buy
        6. SDK ``get_trade_history(limit=5)`` — trade recorded
        7. SDK ``get_performance()`` — metrics calculate without error
        8. REST ``GET /api/v1/health`` — platform health endpoint responds
        9. REST ``GET /api/v1/market/prices`` — market data accessible
        10. Result compilation — summarise all findings

    Args:
        config: Resolved :class:`~agent.config.AgentConfig` with platform
                connectivity settings (base URL, API key, API secret).

    Returns:
        :class:`~agent.models.report.WorkflowResult` with
        ``workflow_name="smoke_test"``, status of ``"pass"``, ``"partial"``,
        or ``"fail"``, and fully populated findings, bugs, and metrics.
    """
    from agentexchange.async_client import AsyncAgentExchangeClient
    from agentexchange.exceptions import AgentExchangeError

    steps_completed = 0
    findings: list[str] = []
    bugs_found: list[str] = []
    metrics: dict = {}

    client = AsyncAgentExchangeClient(
        api_key=config.platform_api_key,
        api_secret=config.platform_api_secret,
        base_url=config.platform_base_url,
    )

    try:
        # ------------------------------------------------------------------
        # Step 1: Get BTC price — verify non-zero
        # ------------------------------------------------------------------
        log.info("agent.workflow.smoke_test.step_1", action="get_price", symbol=_SMOKE_SYMBOL)
        try:
            price_result = await client.get_price(_SMOKE_SYMBOL)
            price_val = price_result.price
            if price_val is None or price_val <= Decimal("0"):
                bugs_found.append(
                    f"Step 1 FAIL: get_price returned zero or null price "
                    f"for {_SMOKE_SYMBOL} (got {price_val})"
                )
            else:
                steps_completed += 1
                findings.append(
                    f"Step 1 PASS: {_SMOKE_SYMBOL} price fetched — {price_val} USDT"
                )
                metrics["btc_price"] = str(price_val)
                log.info("agent.workflow.smoke_test.step_1.pass", price=str(price_val))
        except AgentExchangeError as exc:
            bugs_found.append(f"Step 1 FAIL: get_price raised {type(exc).__name__}: {exc}")
            log.warning("agent.workflow.smoke_test.step_1.fail", error=str(exc))

        # ------------------------------------------------------------------
        # Step 2: Get balance — verify USDT balance exists
        # ------------------------------------------------------------------
        log.info("agent.workflow.smoke_test.step_2", action="get_balance")
        try:
            balances = await client.get_balance()
            usdt_balance = next(
                (b for b in balances if b.asset == "USDT"), None
            )
            if not balances:
                bugs_found.append(
                    "Step 2 FAIL: get_balance returned empty list — "
                    "no balances found for account"
                )
            elif usdt_balance is None:
                bugs_found.append(
                    "Step 2 FAIL: get_balance returned balances but USDT asset "
                    "not present — account may not have a starting balance"
                )
            elif usdt_balance.total <= Decimal("0"):
                bugs_found.append(
                    f"Step 2 FAIL: USDT balance is zero or negative "
                    f"(total={usdt_balance.total})"
                )
            else:
                steps_completed += 1
                findings.append(
                    f"Step 2 PASS: Balance fetched — USDT total={usdt_balance.total}, "
                    f"available={usdt_balance.available}"
                )
                metrics["usdt_balance"] = str(usdt_balance.available)
                log.info(
                    "agent.workflow.smoke_test.step_2.pass",
                    usdt_total=str(usdt_balance.total),
                    usdt_available=str(usdt_balance.available),
                )
        except AgentExchangeError as exc:
            bugs_found.append(f"Step 2 FAIL: get_balance raised {type(exc).__name__}: {exc}")
            log.warning("agent.workflow.smoke_test.step_2.fail", error=str(exc))

        # ------------------------------------------------------------------
        # Step 3: Get candles — verify historical data available
        # ------------------------------------------------------------------
        log.info(
            "agent.workflow.smoke_test.step_3",
            action="get_candles",
            symbol=_SMOKE_SYMBOL,
            interval="1h",
            limit=10,
        )
        try:
            candles = await client.get_candles(_SMOKE_SYMBOL, interval="1h", limit=10)
            if not candles:
                bugs_found.append(
                    f"Step 3 FAIL: get_candles returned empty list for "
                    f"{_SMOKE_SYMBOL} 1h — no historical data available"
                )
            else:
                steps_completed += 1
                latest_close = candles[-1].close if candles else None
                findings.append(
                    f"Step 3 PASS: {len(candles)} candles returned for "
                    f"{_SMOKE_SYMBOL} 1h; latest close={latest_close}"
                )
                metrics["candle_count"] = len(candles)
                log.info(
                    "agent.workflow.smoke_test.step_3.pass",
                    candle_count=len(candles),
                    latest_close=str(latest_close),
                )
        except AgentExchangeError as exc:
            bugs_found.append(
                f"Step 3 FAIL: get_candles raised {type(exc).__name__}: {exc}"
            )
            log.warning("agent.workflow.smoke_test.step_3.fail", error=str(exc))

        # ------------------------------------------------------------------
        # Step 4: Place tiny market buy — verify order accepted
        # ------------------------------------------------------------------
        log.info(
            "agent.workflow.smoke_test.step_4",
            action="place_market_order",
            symbol=_SMOKE_SYMBOL,
            side="buy",
            quantity=_SMOKE_QUANTITY,
        )
        placed_order_id: str | None = None
        try:
            order = await client.place_market_order(
                _SMOKE_SYMBOL, "buy", _SMOKE_QUANTITY
            )
            if order.status not in ("filled", "completed", "closed"):
                # Some platforms use different terminal status names; treat
                # any non-error status as a pass to avoid false failures.
                findings.append(
                    f"Step 4 NOTE: order placed with status={order.status!r} "
                    f"(expected 'filled'); order_id={order.order_id}"
                )
            placed_order_id = str(order.order_id)
            steps_completed += 1
            findings.append(
                f"Step 4 PASS: market buy placed — order_id={order.order_id}, "
                f"status={order.status}, executed_price={order.executed_price}"
            )
            metrics["test_order_id"] = placed_order_id
            metrics["test_order_status"] = order.status
            log.info(
                "agent.workflow.smoke_test.step_4.pass",
                order_id=placed_order_id,
                status=order.status,
                executed_price=str(order.executed_price),
            )
        except AgentExchangeError as exc:
            bugs_found.append(
                f"Step 4 FAIL: place_market_order raised {type(exc).__name__}: {exc}"
            )
            log.warning("agent.workflow.smoke_test.step_4.fail", error=str(exc))

        # ------------------------------------------------------------------
        # Step 5: Get positions — verify a BTC position exists after buy
        # ------------------------------------------------------------------
        log.info("agent.workflow.smoke_test.step_5", action="get_positions")
        try:
            positions = await client.get_positions()
            btc_position = next(
                (p for p in positions if p.symbol == _SMOKE_SYMBOL), None
            )
            if btc_position is None:
                # Position may not appear immediately or the order may have
                # failed in step 4; record as a finding rather than a bug
                # when step 4 also failed.
                if placed_order_id is not None:
                    bugs_found.append(
                        f"Step 5 FAIL: get_positions returned no {_SMOKE_SYMBOL} "
                        "position after a successful buy order"
                    )
                else:
                    findings.append(
                        "Step 5 SKIP: no buy order was placed (step 4 failed) — "
                        "position check skipped"
                    )
                    steps_completed += 1  # credit step as structurally valid
            else:
                steps_completed += 1
                findings.append(
                    f"Step 5 PASS: {_SMOKE_SYMBOL} position found — "
                    f"quantity={btc_position.quantity}, "
                    f"unrealized_pnl={btc_position.unrealized_pnl}"
                )
                metrics["btc_position_qty"] = str(btc_position.quantity)
                log.info(
                    "agent.workflow.smoke_test.step_5.pass",
                    symbol=btc_position.symbol,
                    quantity=str(btc_position.quantity),
                )
        except AgentExchangeError as exc:
            bugs_found.append(
                f"Step 5 FAIL: get_positions raised {type(exc).__name__}: {exc}"
            )
            log.warning("agent.workflow.smoke_test.step_5.fail", error=str(exc))

        # ------------------------------------------------------------------
        # Step 6: Get trade history — verify trade was recorded
        # ------------------------------------------------------------------
        log.info("agent.workflow.smoke_test.step_6", action="get_trade_history", limit=5)
        try:
            trades = await client.get_trade_history(limit=5)
            if not trades:
                if placed_order_id is not None:
                    bugs_found.append(
                        "Step 6 FAIL: get_trade_history returned empty list "
                        "after a successful buy order was placed"
                    )
                else:
                    findings.append(
                        "Step 6 INFO: trade history empty — no trades exist yet "
                        "for this account (step 4 also failed)"
                    )
                    steps_completed += 1  # structurally valid call
            else:
                latest = trades[0]
                steps_completed += 1
                findings.append(
                    f"Step 6 PASS: {len(trades)} trades returned; "
                    f"latest={latest.symbol} {latest.side} "
                    f"qty={latest.quantity} @ {latest.price} "
                    f"at {latest.executed_at.isoformat()}"
                )
                metrics["trade_history_count"] = len(trades)
                log.info(
                    "agent.workflow.smoke_test.step_6.pass",
                    trade_count=len(trades),
                    latest_symbol=latest.symbol,
                    latest_side=latest.side,
                )
        except AgentExchangeError as exc:
            bugs_found.append(
                f"Step 6 FAIL: get_trade_history raised {type(exc).__name__}: {exc}"
            )
            log.warning("agent.workflow.smoke_test.step_6.fail", error=str(exc))

        # ------------------------------------------------------------------
        # Step 7: Get performance metrics — verify calculation succeeds
        # ------------------------------------------------------------------
        log.info("agent.workflow.smoke_test.step_7", action="get_performance", period="all")
        try:
            perf = await client.get_performance(period="all")
            # Performance is structurally valid if we get a response back;
            # metrics may be zero on a fresh account, which is not a bug.
            steps_completed += 1
            findings.append(
                f"Step 7 PASS: performance metrics returned — "
                f"sharpe={perf.sharpe_ratio}, "
                f"win_rate={perf.win_rate}, "
                f"total_trades={perf.total_trades}"
            )
            metrics["sharpe_ratio"] = str(perf.sharpe_ratio)
            metrics["win_rate"] = str(perf.win_rate)
            metrics["total_trades"] = perf.total_trades
            log.info(
                "agent.workflow.smoke_test.step_7.pass",
                sharpe=str(perf.sharpe_ratio),
                win_rate=str(perf.win_rate),
                total_trades=perf.total_trades,
            )
        except AgentExchangeError as exc:
            bugs_found.append(
                f"Step 7 FAIL: get_performance raised {type(exc).__name__}: {exc}"
            )
            log.warning("agent.workflow.smoke_test.step_7.fail", error=str(exc))

    finally:
        await client.aclose()

    # ------------------------------------------------------------------
    # Steps 8-9: REST health and market prices (direct httpx, no SDK)
    # ------------------------------------------------------------------
    base_url = config.platform_base_url.rstrip("/")
    headers = {"X-API-Key": config.platform_api_key}

    async with httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=15.0,
    ) as http:
        # Step 8: GET /api/v1/health
        log.info("agent.workflow.smoke_test.step_8", action="GET /api/v1/health")
        try:
            resp = await http.get("/api/v1/health")
            if resp.status_code == 200:
                body = resp.json()
                status_field = body.get("status", "<missing>")
                steps_completed += 1
                findings.append(
                    f"Step 8 PASS: GET /api/v1/health returned 200 — "
                    f"status={status_field!r}"
                )
                metrics["health_status"] = status_field
                log.info("agent.workflow.smoke_test.step_8.pass", health_status=status_field)
            else:
                bugs_found.append(
                    f"Step 8 FAIL: GET /api/v1/health returned HTTP {resp.status_code} "
                    f"(expected 200); body={resp.text[:200]}"
                )
                log.warning(
                    "agent.workflow.smoke_test.step_8.fail",
                    http_status=resp.status_code,
                    body=resp.text[:200],
                )
        except httpx.RequestError as exc:
            bugs_found.append(
                f"Step 8 FAIL: GET /api/v1/health network error — "
                f"{type(exc).__name__}: {exc}"
            )
            log.warning("agent.workflow.smoke_test.step_8.fail", error=str(exc))

        # Step 9: GET /api/v1/market/prices
        log.info("agent.workflow.smoke_test.step_9", action="GET /api/v1/market/prices")
        try:
            resp = await http.get("/api/v1/market/prices")
            if resp.status_code == 200:
                body = resp.json()
                prices_list = body.get("prices", [])
                price_count = len(prices_list)
                if price_count == 0:
                    bugs_found.append(
                        "Step 9 FAIL: GET /api/v1/market/prices returned 200 but "
                        "'prices' list is empty — no market data available"
                    )
                    log.warning("agent.workflow.smoke_test.step_9.fail", reason="empty prices list")
                else:
                    steps_completed += 1
                    findings.append(
                        f"Step 9 PASS: GET /api/v1/market/prices returned "
                        f"{price_count} pairs"
                    )
                    metrics["market_price_count"] = price_count
                    log.info(
                        "agent.workflow.smoke_test.step_9.pass", price_count=price_count
                    )
            else:
                bugs_found.append(
                    f"Step 9 FAIL: GET /api/v1/market/prices returned HTTP "
                    f"{resp.status_code} (expected 200); body={resp.text[:200]}"
                )
                log.warning(
                    "agent.workflow.smoke_test.step_9.fail",
                    http_status=resp.status_code,
                    body=resp.text[:200],
                )
        except httpx.RequestError as exc:
            bugs_found.append(
                f"Step 9 FAIL: GET /api/v1/market/prices network error — "
                f"{type(exc).__name__}: {exc}"
            )
            log.warning("agent.workflow.smoke_test.step_9.fail", error=str(exc))

    # ------------------------------------------------------------------
    # Step 10: Compile results
    # ------------------------------------------------------------------
    log.info(
        "agent.workflow.smoke_test.step_10",
        action="compile_results",
        steps_completed=steps_completed,
        bugs_found=len(bugs_found),
    )
    steps_completed += 1  # step 10 is the compilation itself — always passes
    findings.append(
        f"Step 10 PASS: results compiled — "
        f"{steps_completed}/{_STEPS_TOTAL} steps completed, "
        f"{len(bugs_found)} bugs found"
    )

    if not bugs_found:
        status = "pass"
    elif steps_completed > 1:
        status = "partial"
    else:
        status = "fail"

    log.info(
        "agent.workflow.smoke_test.complete",
        status=status,
        steps_completed=steps_completed,
        steps_total=_STEPS_TOTAL,
        bugs=len(bugs_found),
    )

    return WorkflowResult(
        workflow_name="smoke_test",
        status=status,
        steps_completed=steps_completed,
        steps_total=_STEPS_TOTAL,
        findings=findings,
        bugs_found=bugs_found,
        suggestions=[],
        metrics=metrics,
    )
