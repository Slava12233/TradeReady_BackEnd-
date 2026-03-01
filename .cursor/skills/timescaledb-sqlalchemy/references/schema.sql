-- AiTradingAgent TimescaleDB Schema
-- Extensions
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Tables
CREATE TABLE accounts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key           VARCHAR(64) UNIQUE NOT NULL,
    api_key_hash      VARCHAR(128) NOT NULL,
    api_secret_hash   VARCHAR(128) NOT NULL,
    display_name      VARCHAR(100) NOT NULL,
    email             VARCHAR(255),
    starting_balance  NUMERIC(20,8) NOT NULL DEFAULT 10000.00,
    status            VARCHAR(20) NOT NULL DEFAULT 'active',
    risk_profile      JSONB DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE balances (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id  UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    asset       VARCHAR(20) NOT NULL,
    available   NUMERIC(20,8) NOT NULL DEFAULT 0 CHECK (available >= 0),
    locked      NUMERIC(20,8) NOT NULL DEFAULT 0 CHECK (locked >= 0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_id, asset)
);
CREATE INDEX idx_balances_account ON balances(account_id);

CREATE TABLE trading_sessions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id        UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    starting_balance  NUMERIC(20,8) NOT NULL,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at          TIMESTAMPTZ,
    ending_equity     NUMERIC(20,8),
    status            VARCHAR(20) NOT NULL DEFAULT 'active'
);
CREATE INDEX idx_sessions_account ON trading_sessions(account_id);

CREATE TABLE orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    session_id      UUID REFERENCES trading_sessions(id),
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(4) NOT NULL CHECK (side IN ('buy', 'sell')),
    type            VARCHAR(20) NOT NULL CHECK (type IN ('market', 'limit', 'stop_loss', 'take_profit')),
    quantity        NUMERIC(20,8) NOT NULL CHECK (quantity > 0),
    price           NUMERIC(20,8),
    executed_price  NUMERIC(20,8),
    executed_qty    NUMERIC(20,8),
    slippage_pct    NUMERIC(10,6),
    fee             NUMERIC(20,8),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'filled', 'partially_filled', 'cancelled', 'rejected', 'expired')),
    rejection_reason VARCHAR(100),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at       TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ
);
CREATE INDEX idx_orders_account ON orders(account_id);
CREATE INDEX idx_orders_account_status ON orders(account_id, status);
CREATE INDEX idx_orders_symbol_status ON orders(symbol, status) WHERE status = 'pending';

CREATE TABLE trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    order_id        UUID NOT NULL REFERENCES orders(id),
    session_id      UUID REFERENCES trading_sessions(id),
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(4) NOT NULL,
    quantity        NUMERIC(20,8) NOT NULL,
    price           NUMERIC(20,8) NOT NULL,
    quote_amount    NUMERIC(20,8) NOT NULL,
    fee             NUMERIC(20,8) NOT NULL,
    realized_pnl    NUMERIC(20,8),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_trades_account ON trades(account_id);
CREATE INDEX idx_trades_account_time ON trades(account_id, created_at DESC);
CREATE INDEX idx_trades_symbol ON trades(symbol, created_at DESC);

CREATE TABLE positions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(4) NOT NULL DEFAULT 'long',
    quantity        NUMERIC(20,8) NOT NULL DEFAULT 0,
    avg_entry_price NUMERIC(20,8) NOT NULL,
    total_cost      NUMERIC(20,8) NOT NULL,
    realized_pnl    NUMERIC(20,8) NOT NULL DEFAULT 0,
    opened_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_id, symbol)
);
CREATE INDEX idx_positions_account ON positions(account_id);

CREATE TABLE ticks (
    time            TIMESTAMPTZ NOT NULL,
    symbol          TEXT NOT NULL,
    price           NUMERIC(20,8) NOT NULL,
    quantity        NUMERIC(20,8) NOT NULL,
    is_buyer_maker  BOOLEAN NOT NULL DEFAULT FALSE,
    trade_id        BIGINT NOT NULL
);
SELECT create_hypertable('ticks', 'time', chunk_time_interval => INTERVAL '1 hour');
CREATE INDEX idx_ticks_symbol_time ON ticks (symbol, time DESC);
ALTER TABLE ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('ticks', INTERVAL '7 days');
SELECT add_retention_policy('ticks', INTERVAL '90 days');

CREATE TABLE portfolio_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    snapshot_type   VARCHAR(10) NOT NULL CHECK (snapshot_type IN ('minute', 'hourly', 'daily')),
    total_equity    NUMERIC(20,8) NOT NULL,
    available_cash  NUMERIC(20,8) NOT NULL,
    position_value  NUMERIC(20,8) NOT NULL,
    unrealized_pnl  NUMERIC(20,8) NOT NULL,
    realized_pnl    NUMERIC(20,8) NOT NULL,
    positions       JSONB,
    metrics         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_snapshots_account_type ON portfolio_snapshots(account_id, snapshot_type, created_at DESC);
SELECT create_hypertable('portfolio_snapshots', 'created_at', chunk_time_interval => INTERVAL '1 day');

CREATE TABLE trading_pairs (
    symbol          VARCHAR(20) PRIMARY KEY,
    base_asset      VARCHAR(10) NOT NULL,
    quote_asset     VARCHAR(10) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    min_qty         NUMERIC(20,8),
    max_qty         NUMERIC(20,8),
    step_size       NUMERIC(20,8),
    min_notional    NUMERIC(20,8),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    account_id  UUID REFERENCES accounts(id),
    action      VARCHAR(50) NOT NULL,
    details     JSONB,
    ip_address  INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_account ON audit_log(account_id, created_at DESC);

-- Continuous Aggregates
CREATE MATERIALIZED VIEW candles_1m WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', time) AS bucket, symbol,
    FIRST(price, time) AS open, MAX(price) AS high, MIN(price) AS low,
    LAST(price, time) AS close, SUM(quantity) AS volume, COUNT(*) AS trade_count
FROM ticks GROUP BY bucket, symbol WITH NO DATA;
SELECT add_continuous_aggregate_policy('candles_1m',
    start_offset => INTERVAL '10 minutes', end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');

CREATE MATERIALIZED VIEW candles_5m WITH (timescaledb.continuous) AS
SELECT time_bucket('5 minutes', time) AS bucket, symbol,
    FIRST(price, time) AS open, MAX(price) AS high, MIN(price) AS low,
    LAST(price, time) AS close, SUM(quantity) AS volume, COUNT(*) AS trade_count
FROM ticks GROUP BY bucket, symbol WITH NO DATA;
SELECT add_continuous_aggregate_policy('candles_5m',
    start_offset => INTERVAL '30 minutes', end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes');

CREATE MATERIALIZED VIEW candles_1h WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', time) AS bucket, symbol,
    FIRST(price, time) AS open, MAX(price) AS high, MIN(price) AS low,
    LAST(price, time) AS close, SUM(quantity) AS volume, COUNT(*) AS trade_count
FROM ticks GROUP BY bucket, symbol WITH NO DATA;
SELECT add_continuous_aggregate_policy('candles_1h',
    start_offset => INTERVAL '4 hours', end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');

CREATE MATERIALIZED VIEW candles_1d WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', time) AS bucket, symbol,
    FIRST(price, time) AS open, MAX(price) AS high, MIN(price) AS low,
    LAST(price, time) AS close, SUM(quantity) AS volume, COUNT(*) AS trade_count
FROM ticks GROUP BY bucket, symbol WITH NO DATA;
SELECT add_continuous_aggregate_policy('candles_1d',
    start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day');
