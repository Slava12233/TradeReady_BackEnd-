# API Schemas

<!-- last-updated: 2026-04-07 (V.0.0.3) -->

> Pydantic v2 request/response schemas for every REST API endpoint, with strict Decimal-as-string serialization and consistent validation patterns.

## What This Module Does

This package defines all Pydantic v2 `BaseModel` subclasses used as request bodies and response bodies across the REST API. Every schema enforces input validation (field constraints, cross-field rules) and output serialization (Decimal to string, optional-field nullability). Route handlers type-hint their parameters and return values with these schemas, and FastAPI auto-generates OpenAPI docs from them.

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package docstring only; no re-exports |
| `account.py` | Account info, balances, positions, portfolio, PnL, reset (`/account/*`) |
| `agents.py` | Agent CRUD, credentials, overview (`/agents/*`) |
| `analytics.py` | Performance metrics, portfolio history, leaderboard (`/analytics/*`) |
| `auth.py` | Register, login (API key + password), JWT token (`/auth/*`) |
| `backtest.py` | Backtest lifecycle, sandbox trading, results, comparison (`/backtest/*`) |
| `battles.py` | Battle CRUD, participants, live/results/replay, historical steps (`/battles/*`) |
| `strategies.py` | Strategy CRUD, versions, deploy/undeploy (`/strategies/*`) |
| `strategy_tests.py` | Strategy test runs, results, version comparison (`/strategies/*/test*`) |
| `training.py` | Training runs, episodes, learning curves, comparison (`/training/*`) |
| `market.py` | Pairs, prices, tickers, candles, public trades, order book (`/market/*`) |
| `trading.py` | Order placement, order detail/list, cancel, trade history (`/trade/*`) |
| `waitlist.py` | Waitlist subscription (`/waitlist/*`) |
| `indicators.py` | Indicator compute request + named-array response (`/indicators/*`) |
| `metrics.py` | Agent metrics response, deflated Sharpe fields, compare response (`/metrics/*`) |
| `webhooks.py` | `WebhookCreate`, `WebhookUpdate`, `WebhookResponse`, `WebhookDeliveryLog` (`/webhooks/*`) |
| `strategies_compare.py` | Strategy comparison response — side-by-side metrics for up to 5 strategies |
| `backtest_batch_fast.py` | `BatchStepResult` schema — steps_completed, virtual_time, progress_pct, fills_count, final_portfolio |

## Architecture & Patterns

### Base Schema

Every file defines a private `_BaseSchema(BaseModel)` with shared config. This base class is **duplicated per file** rather than imported from a shared location:

```python
class _BaseSchema(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,    # Accept both alias and field name
        str_strip_whitespace=True, # Auto-strip whitespace on string inputs
    )
```

All schemas in the file inherit from the local `_BaseSchema`.

### Decimal Serialization

Every `Decimal` field is serialized to `str` in JSON output via `@field_serializer`. This preserves full `NUMERIC(20,8)` precision and avoids floating-point rounding in JSON. The pattern is:

```python
# Single field
@field_serializer("starting_balance")
def _serialize_balance(self, value: Decimal) -> str:
    return str(value)

# Multiple fields
@field_serializer("quantity", "price", "fee", "total")
def _serialize_decimal(self, value: Decimal) -> str:
    return str(value)

# Nullable fields
@field_serializer("snapshot_balance", "final_equity")
def _serialize_decimal(self, value: Decimal | None) -> str | None:
    return str(value) if value is not None else None
```

The serializer method names are conventionally `_serialize_decimal`, `_serialize_balance`, `_serialize_price`, etc. The `# noqa: PLR6301` comment suppresses the "method could be a function" lint since `@field_serializer` requires an instance method.

### Field Definitions

All fields use `pydantic.Field(...)` with:
- `description` -- always present, feeds into OpenAPI docs
- `examples` -- always present, feeds into Swagger "Try it out"
- Numeric constraints: `gt`, `ge`, `le`, `min_length`, `max_length` where applicable
- `default` or `default_factory` for optional/list fields

Required fields use `Field(...)` (ellipsis). Optional fields use `Field(default=None, ...)` or union type `T | None`.

### Literal Type Aliases

Domain-specific enumerations use `typing.Literal` aliases defined at module level:

- `account.py`: `AccountStatus = Literal["active", "suspended", "closed"]`, `PnLPeriod = Literal["1d", "7d", "30d", "all"]`
- `analytics.py`: `AnalyticsPeriod = Literal["1d", "7d", "30d", "90d", "all"]`, `SnapshotInterval = Literal["1m", "1h", "1d"]`
- `trading.py`: `OrderSide = Literal["buy", "sell"]`, `OrderType = Literal["market", "limit", "stop_loss", "take_profit"]`, `OrderStatus = Literal["pending", "filled", "partially_filled", "cancelled", "rejected", "expired"]`

### Model Validators

Cross-field validation uses `@model_validator(mode="after")`. The only current usage is in `trading.py`:

```python
@model_validator(mode="after")
def _validate_price_requirement(self) -> OrderRequest:
    """Enforce: limit/stop/TP require price; market forbids price."""
    if self.type in _PRICE_REQUIRED and self.price is None:
        raise ValueError(f"'price' is required for '{self.type}' orders.")
    if self.type == "market" and self.price is not None:
        raise ValueError("'price' must not be set for 'market' orders.")
    return self
```

### Email Validation

`auth.py` and `waitlist.py` use `pydantic.EmailStr` (requires `email-validator` package) for email fields.

### Nested Schemas

Response schemas compose nested models for structured sub-objects:
- `AccountInfoResponse` embeds `SessionInfo` and `RiskProfileInfo`
- `PortfolioResponse` embeds `list[PositionItem]`
- `ResetResponse` embeds `PreviousSessionSummary` and `NewSessionSummary`
- `BattleResponse` embeds `list[BattleParticipantResponse]`
- `BattleListResponse`, `BacktestListResponse`, etc. wrap a list + `total` count

### Loose-Typed Response Schemas

Some schemas (primarily in `backtest.py`) use `dict[str, Any]` or `dict[str, object]` for dynamic/variable-shape data (e.g., `metrics`, `config`). This trades compile-time safety for flexibility where the shape depends on runtime state. Note: `battles.py` live endpoint previously used `dict[str, Any]` for participant data, which caused a frontend crash (2026-04-07) — the live participants are now typed via `BattleLiveParticipantSchema`.

## Public API / Interfaces

Schemas are imported directly by route handlers:

```python
from src.api.schemas.trading import OrderRequest, OrderResponse
from src.api.schemas.account import BalancesResponse
from src.api.schemas.battles import BattleCreate, BattleResponse
```

There are no re-exports from `__init__.py`. Each file is imported individually.

### Request Schemas (used as route handler parameters)

| Schema | File | Endpoint |
|--------|------|----------|
| `RegisterRequest` | `auth.py` | `POST /auth/register` |
| `LoginRequest` | `auth.py` | `POST /auth/login` |
| `UserLoginRequest` | `auth.py` | `POST /auth/user-login` |
| `OrderRequest` | `trading.py` | `POST /trade/order` |
| `ResetRequest` | `account.py` | `POST /account/reset` |
| `AgentCreate` | `agents.py` | `POST /agents` |
| `AgentUpdate` | `agents.py` | `PUT /agents/{id}` |
| `BacktestCreateRequest` | `backtest.py` | `POST /backtest/create` |
| `BacktestStepBatchRequest` | `backtest.py` | `POST /backtest/{id}/step/batch` |
| `BacktestOrderRequest` | `backtest.py` | `POST /backtest/{id}/trade/order` |
| `ModeSwitchRequest` | `backtest.py` | `POST /account/mode` |
| `BattleCreate` | `battles.py` | `POST /battles` |
| `BattleUpdate` | `battles.py` | `PUT /battles/{id}` |
| `AddParticipantRequest` | `battles.py` | `POST /battles/{id}/participants` |
| `HistoricalStepRequest` | `battles.py` | `POST /battles/{id}/step/batch` |
| `HistoricalOrderRequest` | `battles.py` | `POST /battles/{id}/trade/order` |
| `BattleReplayRequest` | `battles.py` | `POST /battles/{id}/replay` |
| `WaitlistRequest` | `waitlist.py` | `POST /waitlist/subscribe` |

## Dependencies

- `pydantic` (v2) -- `BaseModel`, `ConfigDict`, `Field`, `field_serializer`, `model_validator`, `EmailStr`
- `email-validator` -- required by `EmailStr` in `auth.py` and `waitlist.py`
- Standard library: `datetime`, `decimal.Decimal`, `typing.Literal`, `uuid.UUID`
- No internal project imports (schemas are leaf nodes in the dependency graph)

## Common Tasks

### Adding a new schema

1. Identify the correct file based on the API domain (account, trading, market, etc.). Create a new file only if the domain is entirely new.

2. Inherit from the file-local `_BaseSchema`:
   ```python
   class MyNewRequest(_BaseSchema):
       """Request body for ``POST /api/v1/domain/action``."""
       name: str = Field(..., min_length=1, max_length=100, description="...", examples=["..."])
   ```

3. For every `Decimal` field, add a `@field_serializer` that returns `str(value)`. Group multiple Decimal fields into one serializer. For nullable Decimals, return `str(value) if value is not None else None`.

4. Add `description` and `examples` to every `Field()`. Required fields use `Field(...)`, optional use `Field(default=None, ...)`.

5. For cross-field validation, use `@model_validator(mode="after")` and raise `ValueError` on invalid combinations.

6. For enumerated string values, define a `Literal` alias at module level (e.g., `MyStatus = Literal["a", "b"]`), then use it as the field type.

7. Import the schema in the corresponding route file and use it as a type hint on the route handler parameter (request body) or return type (response).

### Adding a field to an existing schema

1. Add the field with `Field(default=..., ...)` -- use a default value to maintain backward compatibility with existing API consumers.
2. If it is a `Decimal`, add it to the nearest `@field_serializer` decorator's field list.
3. Update any tests that construct the schema to include the new field.

## Gotchas & Pitfalls

- **`_BaseSchema` is duplicated per file.** There is no shared base in `__init__.py`. If you need to change the shared config (e.g., add `from_attributes=True`), you must update it in every file.

- **Forward reference in `backtest.py`.** `BacktestListResponse` references `BacktestListItem` which is defined below it. This works because of `from __future__ import annotations` at the top of every file, but removing that import will cause `NameError`.

- **`dict[str, object]` vs `dict[str, Any]`.** Some files use `object` and some use `Any` for the dict value type. Both work at runtime but `object` is stricter for type checkers. Be consistent with the file you are editing.

- **Never use `float` for monetary values.** Always use `Decimal` with a `field_serializer` that converts to `str`. The database uses `NUMERIC(20,8)` and `float` would introduce rounding errors.

- **`@field_serializer` requires instance method.** The methods are decorated with `# noqa: PLR6301` to suppress the ruff "could be static" warning. Do not convert them to `@staticmethod`.

- **`OrderResponse` has two sets of optional fields** -- one set for filled orders (executed_price, fee, etc.) and one for pending orders (price, locked_amount, etc.). Both are nullable; the route handler populates whichever set applies.

- **`BacktestCreateRequest.agent_id` is `str | None`**, not `UUID | None`. This is intentional for backward compatibility with string-based agent IDs in the API layer.

- **No re-exports from `__init__.py`.** Import schemas from their specific module, not from the package.

## Recent Changes

- `2026-04-07` (V.0.0.3) — Added 5 new schema files: `indicators.py`, `metrics.py`, `webhooks.py` (`WebhookCreate`, `WebhookUpdate`, `WebhookResponse`, `WebhookDeliveryLog`), `strategies_compare.py`, `backtest_batch_fast.py` (`BatchStepResult`). Updated `<!-- last-updated -->` timestamp.
- `2026-04-07` — `battles.py`: Added typed `BattleLiveParticipantSchema` (13 fields) and updated `BattleLiveResponse` with `elapsed_minutes`, `remaining_minutes`, and `updated_at`. Replaces previous `dict[str, Any]` participant list that had 6 fields with different names than the frontend expected. Fixes live battle UI crash ("Cannot read properties of undefined").
- `2026-04-02` (BUG-015) — `trading.py`: `OrderRequest.price` field now uses `AliasChoices(["price", "stop_price"])` so stop-loss/take-profit orders submitted with the `stop_price` key are accepted without a 422 validation error.
- `2026-04-02` (BUG-001) — `auth.py`: `RegisterResponse` gained two new optional fields: `agent_id: UUID | None` and `agent_api_key: str | None`. These are populated by `AccountService.register()` when the auto-created default agent succeeds. Clients should use `agent_api_key` as `X-API-Key` for all trading endpoints going forward.
- `2026-03-17` -- Initial CLAUDE.md created
