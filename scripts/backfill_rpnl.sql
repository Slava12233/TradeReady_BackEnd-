DO $$
DECLARE
    rec RECORD;
    pos_qty   NUMERIC(20,8);
    pos_avg   NUMERIC(20,8);
    old_cost  NUMERIC(20,8);
    new_qty   NUMERIC(20,8);
    new_cost  NUMERIC(20,8);
    rpnl      NUMERIC(20,8);
    cur_key   TEXT := '';
    updated   INT := 0;
BEGIN
    FOR rec IN
        SELECT id, account_id, symbol, side, quantity, price
        FROM trades
        ORDER BY account_id, symbol, created_at ASC
    LOOP
        IF cur_key != rec.account_id::text || '|' || rec.symbol THEN
            cur_key := rec.account_id::text || '|' || rec.symbol;
            pos_qty := 0;
            pos_avg := 0;
        END IF;

        IF rec.side = 'buy' THEN
            old_cost := pos_qty * pos_avg;
            new_qty  := pos_qty + rec.quantity;
            new_cost := old_cost + (rec.quantity * rec.price);
            IF new_qty > 0 THEN
                pos_avg := new_cost / new_qty;
            ELSE
                pos_avg := 0;
            END IF;
            pos_qty := new_qty;
        ELSE
            rpnl    := (rec.price - pos_avg) * rec.quantity;
            new_qty := pos_qty - rec.quantity;
            IF new_qty < 0 THEN new_qty := 0; END IF;
            IF new_qty = 0 THEN pos_avg := 0; END IF;
            pos_qty := new_qty;

            UPDATE trades SET realized_pnl = rpnl WHERE id = rec.id;
            updated := updated + 1;
        END IF;
    END LOOP;

    RAISE NOTICE 'Backfill complete: updated % sell trades with realized_pnl', updated;
END $$;
