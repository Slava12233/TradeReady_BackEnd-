# Webhooks

<!-- last-updated: 2026-04-07 -->

> Outbound webhook dispatcher that fires HTTP POST callbacks to user-configured URLs when platform events occur (backtest complete, strategy deployed, battle complete, etc.).

## What This Module Does

The `src/webhooks/` package provides a lightweight event-dispatch system. When a significant platform event occurs, the service calls `fire_event()`, which validates the target URL (SSRF protection), enqueues a Celery task, and the worker POSTs a JSON payload to the user-registered endpoint. HMAC-SHA256 request signing lets receivers verify authenticity.

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Re-exports `fire_event`, `validate_webhook_url` |
| `dispatcher.py` | `fire_event()` — builds payload, validates URL, enqueues Celery task. `validate_webhook_url()` — SSRF protection (blocks private IP ranges, localhost, metadata endpoints) |

## Related Files (outside this package)

| File | Purpose |
|------|---------|
| `src/tasks/webhook_tasks.py` | Celery task `deliver_webhook` — performs HTTP POST with retry and HMAC signature |
| `src/api/routes/webhooks.py` | 6 REST endpoints for webhook CRUD + test delivery |
| `src/api/schemas/webhooks.py` | Pydantic schemas: `WebhookCreate`, `WebhookUpdate`, `WebhookResponse`, `WebhookDeliveryLog` |

## Architecture & Patterns

### Event Flow

```
Platform event occurs
  → service calls fire_event(event_type, payload, account_id)
  → dispatcher validates registered webhook URLs (SSRF check)
  → Celery task enqueued: deliver_webhook.delay(url, payload, secret)
  → worker POSTs JSON to target URL with HMAC-SHA256 signature header
```

### SSRF Protection (`validate_webhook_url`)

`validate_webhook_url()` blocks requests to:
- Private IP ranges (`10.x`, `172.16-31.x`, `192.168.x`, `127.x`)
- Localhost and loopback aliases
- AWS/GCP/Azure instance metadata endpoints (`169.254.169.254`, etc.)
- Non-HTTP/HTTPS schemes

All blocked URLs raise `WebhookValidationError` before any network call is made.

### HMAC Request Signing

Each webhook delivery includes an `X-Signature-256` header:
```
X-Signature-256: sha256=<hex_digest>
```
The digest is computed over the raw JSON body using the webhook secret (stored hashed, revealed once at creation). Receivers can verify the payload has not been tampered with.

### Retry Policy

`deliver_webhook` (Celery task) retries up to 3 times with exponential backoff (10s, 60s, 300s) on non-2xx HTTP responses or network errors. Permanent failures (4xx) are not retried after the first attempt.

## Public API

### dispatcher.py

```python
async def fire_event(
    event_type: str,
    payload: dict,
    account_id: uuid.UUID,
    db: AsyncSession,
) -> int:
    """
    Look up registered webhooks for the account, validate each URL, and
    enqueue a Celery delivery task for each active webhook subscribed to
    event_type. Returns the number of tasks enqueued.
    """

def validate_webhook_url(url: str) -> None:
    """
    Raise WebhookValidationError if url fails SSRF safety checks.
    Blocks private IPs, localhost, metadata endpoints, non-HTTP schemes.
    """
```

### Supported Event Types

| Event | When Fired |
|-------|-----------|
| `backtest.completed` | `BacktestEngine.complete()` |
| `strategy.test.completed` | `aggregate_test_results` Celery task |
| `strategy.deployed` | `StrategyService.deploy()` |
| `battle.completed` | `BattleService.stop()` |

### REST Endpoints (`src/api/routes/webhooks.py`) — 6 endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/webhooks` | Register webhook (returns secret once) |
| `GET` | `/api/v1/webhooks` | List webhooks for account |
| `GET` | `/api/v1/webhooks/{id}` | Webhook detail |
| `PUT` | `/api/v1/webhooks/{id}` | Update URL or subscribed events |
| `DELETE` | `/api/v1/webhooks/{id}` | Delete webhook |
| `POST` | `/api/v1/webhooks/{id}/test` | Send a test event to the URL |

## Dependencies

**Internal:**
- `src.utils.exceptions` — `WebhookValidationError`
- `src.database.models` — `Webhook`, `WebhookDelivery`
- `src.tasks.webhook_tasks` — `deliver_webhook` Celery task

**External:**
- `httpx` — async HTTP client used by `deliver_webhook` for outbound POST
- `hmac`, `hashlib` — stdlib, for HMAC-SHA256 signing

## Gotchas

- **Secret is shown once**: The raw webhook secret is returned only at creation (`POST /webhooks`). The DB stores a bcrypt hash. There is no recovery — users must delete and re-create the webhook if the secret is lost.
- **SSRF check is DNS-agnostic**: The validator resolves the hostname and checks the resulting IP. A hostname that resolves to a private IP is blocked even if the URL looks public. This adds a DNS round-trip at registration time.
- **`fire_event` is async but non-blocking**: It enqueues Celery tasks and returns immediately. The platform event proceeds regardless of webhook delivery success or failure.
- **Delivery logs are pruned**: `WebhookDelivery` rows older than 30 days are cleaned by the daily `cleanup_old_data` task.

## Recent Changes

- `2026-04-07` — Module created as part of V.0.0.3 endgame improvements. SSRF protection, HMAC signing, 4 event types, 6 REST endpoints, Celery delivery task.
