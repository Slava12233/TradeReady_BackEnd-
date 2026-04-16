# Sub-Report 04: Code Standards Compliance

**Date:** 2026-04-15
**Agent:** code-reviewer
**Overall Status:** PARTIAL

---

## Files Reviewed

| File | Status | Notes |
|------|--------|-------|
| `src/api/routes/auth.py` | Warning | stdlib `logging` instead of `structlog` |
| `src/accounts/service.py` | Pass | Decimal, bcrypt offloaded, error handling correct |
| `src/accounts/auth.py` | Pass | Key generation, bcrypt, JWT all correct |
| `src/api/middleware/auth.py` | Warning | stdlib `logging` instead of `structlog` |
| `src/api/routes/trading.py` | Warning | stdlib `logging`; hardcoded fee fraction duplicated |
| `src/order_engine/engine.py` | Pass | Decimal throughout, agent scoped, structlog |
| `src/risk/manager.py` | Pass | Decimal, 8-step chain, agent scoped, structlog |
| `src/api/routes/market.py` | Medium | `cache._redis` private access; bare `except Exception`; stdlib `logging` |
| `src/cache/price_cache.py` | Pass | Decimal, Redis error handling, structlog |
| `src/api/routes/account.py` | Medium | stdlib `logging`; bare `except Exception` in reset; PnL period approximation |
| `src/portfolio/tracker.py` | Warning | stdlib `logging` instead of `structlog` |

---

## Standards Compliance Summary

| Area | Status | Issues |
|------|--------|--------|
| Error handling | PARTIAL | Bare `except Exception` in 3 customer-facing routes; missing exc_info in some warning paths |
| Money (Decimal) | PASS | All routes, services, and the engine use `Decimal(str(...))` correctly. No float monetary values found in the reviewed files. |
| Agent isolation | PASS | All trading, balance, position, and order queries pass `agent_id` correctly. |
| Response schemas | PARTIAL | All reviewed routes use Pydantic schemas. PnL period filtering is approximate (count-based, not time-based). |
| Input validation | PASS | `OrderRequest` has cross-field model validator; trading schema uses `Literal` types; all paths validate symbol. |
| Auth coverage | PASS | All protected routes use `CurrentAccountDep`/`CurrentAgentDep`. Public paths correctly whitelisted. |
| Logging consistency | FAIL | 7 of 11 reviewed files use stdlib `logging.getLogger` instead of `structlog.get_logger`. Project standard is `structlog` everywhere. |

---

## Issues Found

### HIGH

**H-1 — PnL endpoint uses trade-count approximation instead of time-bounded query**
- **File:** `src/api/routes/account.py:630-635`
- **Description:** `GET /account/pnl?period=7d` fetches the most recent 2000 trades (count cap) and calls it "last 7 days". This is not time-bounded. A high-frequency account whose last 2000 trades all happened today will see a wrong "7d" PnL. A low-frequency account with only 50 trades total in 90 days will see all-time data labeled "1d".
- **Customer impact:** A customer asking "how much did I make in the last week?" gets a wrong answer. This is a visible trust-breaking bug on a financial metric.
- **Fix:** Replace `list_by_account(..., limit=limit_by_period)` with a time-bounded query using `WHERE created_at >= NOW() - INTERVAL '7 days'`. The `_period_to_trade_limit` helper should be removed.

**H-2 — `reset_account` snapshot failure silences all exceptions including DB errors**
- **File:** `src/api/routes/account.py:841-849` and `src/api/routes/account.py:860-862`
- **Description:** Two `except Exception:` blocks around pre-reset portfolio snapshot and session lookup swallow all errors silently, including `DatabaseError`, `SQLAlchemyError`, and connection errors. If the DB is degraded and these fail, the reset continues with stale/default values but the customer receives a "success" response with wrong `previous_session` equity data.
- **Customer impact:** Customer believes their reset happened successfully with correct final equity shown, but the equity figure may be `Decimal(str(account.starting_balance))` (the original starting balance, not the current equity). This is misleading.
- **Fix:** Narrow to `except (CacheError, DatabaseError):` for the portfolio snapshot, or at minimum add `exc_info=True` to the warning log so the error is observable. The session lookup block is less critical but should also be narrowed.

**H-3 — `_compute_staleness` in market.py silently returns `(False, None)` on all errors**
- **File:** `src/api/routes/market.py:787`
- **Description:** The bare `except Exception:` in `_compute_staleness` causes the `/market/prices` endpoint to return `stale=False` even when the Redis connection is completely down. Customers see fresh prices when prices may be hours old.
- **Customer impact:** A customer trading based on "current" prices may act on stale data. The `stale=False` response is actively misleading.
- **Fix:** Change to `except RedisError:` (already imported indirectly via the PriceCache). On a genuine Redis failure, return `(True, None)` — fail conservatively (stale=True) rather than fail open (stale=False).

---

### MEDIUM

**M-1 — `cache._redis` accessed directly from route code, bypassing PriceCache abstraction**
- **File:** `src/api/routes/market.py:732`, `market.py:763`, `market.py:770`
- **Description:** `_get_price_timestamp()` and `_compute_staleness()` call `cache._redis.hget(...)` and `cache._redis.hgetall(...)` directly, bypassing PriceCache's error-handling wrapper. If Redis is unavailable, a raw `RedisError` propagates up rather than being caught and converted.
- **Customer impact:** Calling `/market/price/{symbol}` when Redis is down returns a raw 500 instead of a structured `{"error": {...}}` response.
- **Fix:** Add `get_price_timestamp(symbol)` and `get_prices_meta()` methods to `PriceCache` that wrap these Redis calls in `try/except RedisError`. Routes should call those methods, not `_redis` directly.

**M-2 — Logging inconsistency: stdlib `logging` used in critical customer-facing code paths**
- **Files:** `src/api/routes/auth.py:42`, `src/api/routes/account.py:84`, `src/api/routes/trading.py:67`, `src/api/routes/market.py:59`, `src/api/middleware/auth.py:54`, `src/portfolio/tracker.py:62`
- **Description:** These files use `logging.getLogger(__name__)` instead of the project standard `structlog.get_logger(__name__)`. The project's LoggingMiddleware emits structured JSON; stdlib logging does not inject the request correlation ID or structured fields. Auth failures, trade events, and portfolio reads will not have `request_id` or `account_id` in the emitted log records.
- **Customer impact:** Indirect — support cannot correlate a customer complaint (e.g., "my order was rejected at 14:32") with a specific log entry because auth and trading logs lack the `request_id` set by `LoggingMiddleware`.
- **Fix:** Replace `import logging` + `logger = logging.getLogger(__name__)` with `import structlog` + `logger = structlog.get_logger(__name__)` in all 6 files. Note the structlog API difference: `logger.info("event", key=value)` instead of `logger.info("event", extra={"key": value})`.

**M-3 — `asyncio.get_event_loop()` is deprecated in Python 3.10+ and emits warnings in 3.12**
- **Files:** `src/accounts/service.py:186, 296, 344`, `src/api/routes/auth.py:193`, `src/api/middleware/auth.py:224`
- **Description:** `asyncio.get_event_loop().run_in_executor(...)` is the deprecated pattern. In Python 3.12 (the project target), `get_event_loop()` raises a `DeprecationWarning` when called from a coroutine with no running loop, and will eventually raise `RuntimeError`. The correct replacement is `asyncio.get_running_loop().run_in_executor(...)`.
- **Customer impact:** This works today but will break in a future Python patch release. The auth and login paths are most critical.
- **Fix:** Replace all `asyncio.get_event_loop()` with `asyncio.get_running_loop()` in service and middleware code. These are all called from within running coroutines where a loop is guaranteed.

**M-4 — `account.py` account info response exposes the plaintext `api_key` field**
- **File:** `src/api/routes/account.py:282-290`
- **Description:** `AccountInfoResponse` includes `api_key=account.api_key` in the response. The plaintext API key is stored in the DB for O(1) lookup (per the design). Returning it on `GET /account/info` means every call to this endpoint transmits the credential over the wire. If the account info endpoint is ever called on a shared network (logs, proxies), the API key is leaked.
- **Customer impact:** Increased API key exposure surface. The key should only be returned once at registration and at the explicit `GET /agents/{id}/api-key` endpoint (which presumably requires deliberate intent).
- **Fix:** Remove `api_key` from `AccountInfoResponse`, or at minimum redact it to the first/last N characters (`ak_live_...xxxx`). Alternatively, confirm this is intentional per-design (the CLAUDE.md notes the key is stored plaintext for lookup — returning it in info may be a documented choice).

---

### LOW

**L-1 — Hardcoded fee fraction `0.001` duplicated in trading route**
- **File:** `src/api/routes/trading.py:257, 534, 612`
- **Description:** The fee fraction `0.001` (0.1%) is hardcoded in three places in the trading route (pending order collateral calculation, cancel order unlock calculation, cancel-all unlock calculation). These must match the engine's `_FEE_FRACTION` in `slippage.py`. If the fee changes, the route calculations will produce wrong unlock amounts, confusing customers.
- **Customer impact:** Customer cancels a limit order and the API response shows a different `unlocked_amount` than what actually lands in their balance.
- **Fix:** Extract `_FEE_FRACTION = Decimal("0.001")` as a module-level constant in `trading.py`, or import it from `src.order_engine.slippage`. The same constant in 4 places is a maintenance hazard.

**L-2 — `_period_to_trade_limit` comment acknowledges the flaw but does not track it**
- **File:** `src/api/routes/account.py:742-760`
- **Description:** The docstring explicitly says "This is a coarse approximation — a production system would use time-bounded queries." This is now in production. The comment was acceptable during development but is now customer-facing technical debt.
- **Customer impact:** See H-1 above.
- **Fix:** Addressed by H-1 fix.

**L-3 — `started_at` timezone handling uses `.replace(tzinfo=UTC)` instead of `.astimezone(UTC)`**
- **File:** `src/api/routes/account.py:865-870`
- **Description:** In the reset duration calculation, `started_at.replace(tzinfo=UTC)` is used to attach timezone info. `replace()` does not convert — it forcibly attaches UTC to a naive datetime that may already represent a different timezone if the DB stores local time. `astimezone(UTC)` is the safe form.
- **Customer impact:** Reset response may show `duration_days` off by a few hours for accounts near midnight UTC. Minor but incorrect.
- **Fix:** Replace `.replace(tzinfo=UTC)` with `.astimezone(UTC)` (after checking that the ORM returns timezone-aware datetimes, which TimescaleDB does).

---

## Recommendations

1. **Fix H-1 (PnL period) before launch.** A customer asking "how profitable was my strategy last week?" getting wrong numbers is a direct trust issue. This requires a repository method change, not just a route change.

2. **Fix H-2 and H-3 (silent exception swallowing) before launch.** Financial operations that silently succeed with wrong data are worse than operations that fail with an error message.

3. **Fix M-3 (asyncio.get_event_loop deprecation) before Python 3.12 becomes more strict.** The auth path is in the hot path of every single request.

4. **Address M-2 (structlog consistency) before launch.** Without structured logging in auth and trading routes, production debugging is severely hampered. This is a low-effort fix.

5. **Review M-4 (api_key in /account/info) with the security team.** Whether this is intentional or a credential exposure issue should be a deliberate decision, not an accident.

6. **M-1 (private Redis access) can be fixed post-launch** in the first maintenance window — the risk is observable 500 errors rather than silent wrong data.
