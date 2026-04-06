---
paths:
  - "docker-compose*.yml"
  - "Dockerfile*"
  - ".env*"
  - "src/config.py"
---

# Docker & Environment Variables

## Docker

- `docker-compose.yml` — production setup with all services
- `docker-compose.dev.yml` — development overrides (hot reload, debug ports)
- Healthchecks and resource limits defined for all containers

## Environment Variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | TimescaleDB async connection string |
| `REDIS_URL` | Redis connection string |
| `BINANCE_WS_URL` | Binance WebSocket base URL (legacy fallback) |
| `EXCHANGE_ID` | Primary exchange for CCXT (default `binance`) |
| `EXCHANGE_API_KEY` | Exchange API key for live trading (optional) |
| `EXCHANGE_SECRET` | Exchange API secret for live trading (optional) |
| `ADDITIONAL_EXCHANGES` | Comma-separated extra exchange IDs |
| `JWT_SECRET` | JWT signing secret (64+ chars) |
| `TRADING_FEE_PCT` | Simulated fee (default 0.1%) |
| `DEFAULT_STARTING_BALANCE` | New account balance (default 10000 USDT) |
| `DEFAULT_SLIPPAGE_FACTOR` | Base slippage factor (default 0.1) |
| `CELERY_BROKER_URL` | Celery broker (defaults to `REDIS_URL`) |
| `CELERY_RESULT_BACKEND` | Celery results (defaults to `REDIS_URL`) |
| `TICK_FLUSH_INTERVAL` | Tick buffer flush interval (default 1.0s) |
| `TICK_BUFFER_MAX_SIZE` | Max ticks before forced flush (default 5000) |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend: backend REST API base URL |
| `NEXT_PUBLIC_WS_URL` | Frontend: backend WebSocket URL |
| `OPENROUTER_API_KEY` | Testing agent: OpenRouter API key (in `agent/.env`) |
| `AGENT_MODEL` | Testing agent: primary LLM model ID |
| `AGENT_CHEAP_MODEL` | Testing agent: cheap model for low-stakes tasks |
