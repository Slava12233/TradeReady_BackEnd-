# Order Lifecycle Reference

This document describes the detailed order execution flows for the trading engine.

---

## Market Order Flow

1. **Agent submits** `POST /trade/order` with `type=market`
2. **API Gateway** authenticates and validates the request
3. **Order Engine** receives `OrderRequest`
4. **Risk Manager** validates (chain: account active → daily loss check → rate limit → min size → max size → position limit → open orders count → sufficient balance)
5. **Fetch current price** from Redis: `HGET prices {symbol}`
6. **Calculate slippage**: `execution_price = ref_price * (1 + direction * 0.1 * order_size_usd / avg_daily_volume_usd)`
7. **Calculate fee**: 0.1% of `(quantity * execution_price)`
8. **Execute trade atomically** in DB transaction:
   - **For BUY**: debit `quote_asset` (USDT) by `(quantity * execution_price + fee)`, credit `base_asset` by `quantity`
   - **For SELL**: debit `base_asset` by `quantity`, credit `quote_asset` (USDT) by `(quantity * execution_price - fee)`
9. **Create order record** (`status=filled`), create trade record
10. **Update position** (create or update `avg_entry_price` using weighted average)
11. **Send WebSocket notification** on `"orders"` channel
12. **Portfolio Tracker** recalculates equity

---

## Limit Order Flow

1. **Submit** with `type=limit`, `price` required
2. **Validate** same as market order
3. **Lock required funds**:
   - For buy: lock USDT = `quantity * price + estimated_fee`
   - For sell: lock `base_asset` = `quantity`
4. **Insert order** with `status=pending`
5. **Background matcher** (every 1s) checks:
   - Buy triggers when `current_price <= order.price`
   - Sell triggers when `current_price >= order.price`
6. **On match**: execute same as market order steps 6–12, but using matched price
7. **On cancel**: unlock funds, set `status=cancelled`

---

## Stop-Loss Flow

1. **Submit** with `type=stop_loss`, `price` = trigger price
2. **Validate**, insert as pending
3. **Matcher checks**: triggers when `current_price <= trigger_price` (for sell side)
4. **On trigger**: convert to market order, execute at current price + slippage

---

## Take-Profit Flow

1. **Submit** with `type=take_profit`, `price` = trigger price
2. **Validate**, insert as pending
3. **Matcher checks**: triggers when `current_price >= trigger_price` (for sell side)
4. **On trigger**: convert to market order, execute at current price + slippage

---

## Balance Operation Details

| Operation | Effect |
|-----------|--------|
| `credit(account_id, asset, amount)` | `available += amount` |
| `debit(account_id, asset, amount)` | `available -= amount` (fail if `available < amount`) |
| `lock(account_id, asset, amount)` | `available -= amount`, `locked += amount` |
| `unlock(account_id, asset, amount)` | `locked -= amount`, `available += amount` |

All operations use `SELECT FOR UPDATE` to prevent races.

---

## Position Tracking

| Scenario | Action |
|----------|--------|
| **First buy** of a symbol | Create position with `avg_entry_price = execution_price` |
| **Additional buy** | `avg_entry_price = (old_qty * old_avg + new_qty * new_price) / (old_qty + new_qty)` |
| **Partial sell** | Quantity decreases, `avg_entry_price` unchanged; `realized_pnl += quantity_sold * (sell_price - avg_entry_price)` |
| **Full close** | Record final `realized_pnl`, delete position |
