---
name: trading-engine-logic
description: |
  Teaches the agent how to implement order execution engine logic, slippage,
  risk validation, and balance operations for the crypto trading platform.
  Use when: adding order types, implementing execution flow, configuring risk
  limits, building limit order matching, or working with order_engine/risk/accounts.
---

# Trading Engine Logic

## Order Types

- `MARKET`, `LIMIT`, `STOP_LOSS`, `TAKE_PROFIT`

## Order Lifecycle

```
submit → validate → execute/queue → record → notify
```

## Slippage Model

```
execution_price = ref_price * (1 + direction * factor * order_size_usd / daily_volume_usd)
```

- `direction`: +1 buy, -1 sell
- `factor`: default 0.1
- **Small orders** (<0.01% daily vol): ~0.01% slippage
- **Medium** (0.01–0.1%): ~0.05–0.1%
- **Large** (>0.1%): ~0.1–0.5%

## Trading Fee

- 0.1% of order value.

## Balance Operations

- `credit`, `debit`, `lock`, `unlock` — all atomic via DB transactions.
- **Example** (buy 0.5 BTC at 64000): debit USDT 32000+fee, credit BTC 0.5 — same transaction.

## Risk Validation Chain (Short-Circuit)

Execute in order; stop on first failure:

1. account active
2. daily loss
3. rate limit
4. min size
5. max size
6. position limit
7. open orders
8. balance

## Default Risk Limits

| Limit | Value |
|-------|-------|
| `MAX_POSITION_SIZE_PCT` | 25 |
| `MAX_OPEN_ORDERS` | 50 |
| `DAILY_LOSS_LIMIT_PCT` | 20 |
| `MIN_ORDER_SIZE_USD` | 1.0 |
| `MAX_ORDER_SIZE_PCT` | 50 |
| `ORDER_RATE_LIMIT` | 100/min |

## Circuit Breaker

- Redis hash stores circuit state.
- Trip when daily loss exceeds limit.
- Reset at 00:00 UTC.

## Limit Order Matcher

- Background task every 1s.
- Check pending orders vs current prices.
- Execute when price condition met.

## Implementation Files

- `src/order_engine/`: `engine.py`, `slippage.py`, `matching.py`, `validators.py`
- `src/risk/`: `manager.py`, `circuit_breaker.py`
- `src/accounts/`: `balance_manager.py`

## Checklist

1. Validate order through risk chain before execution.
2. Apply slippage model for market orders.
3. Use atomic DB transactions for balance updates.
4. Run limit matcher every 1s against live prices.
5. Integrate circuit breaker with daily loss tracking.
6. Charge 0.1% fee on each trade.

## References

- For detailed order execution flows, see [references/order-lifecycle.md](references/order-lifecycle.md)
