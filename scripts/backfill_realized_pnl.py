"""Backfill ``realized_pnl`` on existing Trade rows.

The order engine previously created Trade rows without setting realized_pnl.
This script replays trade history per account/symbol chronologically,
tracks a running weighted-average entry price, and computes the realized PnL
for each sell trade using: (sell_price - avg_entry) * quantity.

Buy trades get realized_pnl = 0 (they don't realise PnL — they open positions).

Usage:
    python -m scripts.backfill_realized_pnl [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from decimal import Decimal

import psycopg2

DB_URL = "postgresql://agentexchange:agentexchange_dev_pw@localhost:5432/agentexchange"
ZERO = Decimal("0")


def backfill(dry_run: bool = False) -> None:
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM trades WHERE realized_pnl IS NULL"
    )
    null_count = cur.fetchone()[0]
    print(f"Trades with NULL realized_pnl: {null_count}")

    if null_count == 0:
        print("Nothing to backfill.")
        cur.close()
        conn.close()
        return

    cur.execute("""
        SELECT id, account_id, symbol, side, quantity, price, created_at
        FROM trades
        ORDER BY account_id, symbol, created_at ASC
    """)
    rows = cur.fetchall()
    print(f"Total trades to process: {len(rows)}")

    # Track running position state per (account_id, symbol)
    # Each entry: { "qty": Decimal, "avg_entry": Decimal }
    positions: dict[tuple, dict[str, Decimal]] = defaultdict(
        lambda: {"qty": ZERO, "avg_entry": ZERO}
    )

    updates: list[tuple[Decimal, str]] = []

    for row in rows:
        trade_id, account_id, symbol, side, quantity, price, _ = row
        key = (str(account_id), symbol)
        pos = positions[key]
        quantity = Decimal(str(quantity))
        price = Decimal(str(price))

        if side == "buy":
            old_qty = pos["qty"]
            old_cost = old_qty * pos["avg_entry"]
            new_qty = old_qty + quantity
            new_cost = old_cost + (quantity * price)
            pos["qty"] = new_qty
            pos["avg_entry"] = new_cost / new_qty if new_qty > ZERO else ZERO
            # Buy trades don't realize PnL — but mark them so they're non-NULL
            # (the PnL/performance endpoints filter on realized_pnl IS NOT NULL
            # for counting, so only sells should be counted)
            updates.append((None, str(trade_id)))
        else:  # sell
            avg_entry = pos["avg_entry"]
            rpnl = (price - avg_entry) * quantity
            new_qty = pos["qty"] - quantity
            pos["qty"] = max(new_qty, ZERO)
            if new_qty <= ZERO:
                pos["avg_entry"] = ZERO
            updates.append((rpnl, str(trade_id)))

    sell_updates = [(rpnl, tid) for rpnl, tid in updates if rpnl is not None]
    print(f"Sell trades to update with realized_pnl: {len(sell_updates)}")

    if sell_updates:
        sample = sell_updates[:5]
        print("Sample updates (trade_id, realized_pnl):")
        for rpnl, tid in sample:
            print(f"  {tid}: {rpnl}")

    if dry_run:
        print("\n[DRY RUN] No changes written.")
        cur.close()
        conn.close()
        return

    updated = 0
    for rpnl, tid in sell_updates:
        cur.execute(
            "UPDATE trades SET realized_pnl = %s WHERE id = %s::uuid",
            (rpnl, tid),
        )
        updated += cur.rowcount

    conn.commit()
    print(f"\nBackfill complete. Updated {updated} sell trades with realized_pnl.")

    cur.execute(
        "SELECT COUNT(*) FROM trades WHERE realized_pnl IS NOT NULL"
    )
    filled = cur.fetchone()[0]
    print(f"Trades with realized_pnl set: {filled} / {len(rows)}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill realized_pnl on trades")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    try:
        backfill(dry_run=args.dry_run)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
