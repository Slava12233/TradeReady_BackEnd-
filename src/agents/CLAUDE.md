# Agents Module

<!-- last-updated: 2026-03-19 -->

> Multi-agent creation, lifecycle management, and deterministic avatar generation for the trading platform.

## What This Module Does

This module implements the business-logic layer for managing trading agents. Each account can own multiple agents, each with its own API key, starting USDT balance, risk profile, and trading history. The module also provides deterministic SVG identicon generation so every agent gets a unique, stable visual identity derived from its UUID.

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package marker; no exports. |
| `service.py` | `AgentService` — all agent lifecycle operations (create, clone, reset, archive, delete, API key regeneration). Coordinates `AgentRepository` and `BalanceRepository` within a single DB session/transaction. |
| `avatar_generator.py` | `generate_avatar()` and `generate_color()` — pure functions that produce a deterministic 5x5 symmetric SVG identicon (as a `data:image/svg+xml,...` URI) and a hex color from an agent UUID using MD5 hashing. |

## Architecture & Patterns

- **Session-scoped service**: `AgentService` receives an `AsyncSession` and `Settings` at construction. The caller (FastAPI dependency injection via `src/dependencies.py`) owns the session lifecycle and commit.
- **Ownership checks on every mutation**: All write operations (`update`, `clone`, `reset`, `archive`, `delete`, `regenerate_api_key`) verify `agent.account_id == account_id` before proceeding, raising `PermissionDeniedError` on mismatch.
- **Atomic creation**: `create_agent()` creates the `Agent` row, generates avatar/color, and creates the initial `Balance` row all within one transaction. On `SQLAlchemyError`, the session is rolled back.
- **API key generation offloaded to executor**: `generate_api_credentials()` (bcrypt-based) runs in `run_in_executor` to avoid blocking the async event loop.
- **Frozen dataclass for credentials**: `AgentCredentials` is returned exactly once on creation; the plaintext API key is never stored.

## Public API / Interfaces

### `AgentCredentials` (frozen dataclass)
Returned by `create_agent()` and `clone_agent()`:
- `agent_id: UUID`
- `api_key: str` — plaintext, shown once
- `display_name: str`
- `starting_balance: Decimal`

### `AgentService(session, settings)`
| Method | Signature | Returns |
|--------|-----------|---------|
| `create_agent` | `(account_id, display_name, *, starting_balance?, llm_model?, framework?, strategy_tags?, risk_profile?, color?)` | `AgentCredentials` |
| `get_agent` | `(agent_id)` | `Agent` |
| `list_agents` | `(account_id, *, include_archived?, limit?, offset?)` | `Sequence[Agent]` |
| `update_agent` | `(agent_id, account_id, **fields)` | `Agent` |
| `clone_agent` | `(agent_id, account_id, *, new_name?)` | `AgentCredentials` |
| `reset_agent` | `(agent_id, account_id)` | `Agent` |
| `archive_agent` | `(agent_id, account_id)` | `Agent` |
| `delete_agent` | `(agent_id, account_id)` | `None` |
| `regenerate_api_key` | `(agent_id, account_id)` | `str` (plaintext key) |

### `avatar_generator` module-level functions
| Function | Signature | Returns |
|----------|-----------|---------|
| `generate_avatar` | `(agent_id: UUID, size: int = 80)` | `str` — SVG data URI |
| `generate_color` | `(agent_id: UUID)` | `str` — hex color like `"#a3b2c1"` |

## Dependencies

**Internal imports:**
- `src.accounts.auth.generate_api_credentials` — bcrypt-hashed API key generation
- `src.config.Settings` — `default_starting_balance` and other app config
- `src.database.models.Agent`, `Balance` — SQLAlchemy ORM models
- `src.database.repositories.agent_repo.AgentRepository` — agent CRUD
- `src.database.repositories.balance_repo.BalanceRepository` — balance CRUD
- `src.utils.exceptions.DatabaseError`, `PermissionDeniedError`

**Third-party:**
- `sqlalchemy.ext.asyncio.AsyncSession`
- `structlog` — structured logging

**No external network calls.** Avatar generation is pure computation (MD5 hash of UUID).

## Common Tasks

- **Add a new agent field**: Update `create_agent()` params, pass it through to the `Agent(...)` constructor, and update the corresponding Pydantic schema in `src/api/schemas/agents.py`.
- **Change default starting balance**: Controlled by `Settings.default_starting_balance` in `src/config.py`, not hardcoded here.
- **Change avatar style**: Modify `generate_avatar()` in `avatar_generator.py`. It is a pure function with no side effects, so changes are safe.

## Gotchas & Pitfalls

- **`generate_api_credentials` uses bcrypt** and is CPU-intensive. It is deliberately run via `asyncio.run_in_executor(None, ...)` to avoid blocking the event loop. Do not call it directly in an async context.
- **Caller must commit the session.** `AgentService` calls `flush()` but never `commit()`. The FastAPI dependency layer handles commit/rollback. If you use `AgentService` outside of the DI framework, you must commit manually.
- **`_STARTING_ASSET` is hardcoded to `"USDT"`**. All agents start with USDT only. Multi-asset starting balances are not supported.
- **`reset_agent` deletes all balance rows** for the agent and re-creates a single USDT balance. This wipes any non-USDT holdings without warning.
- **Avatar uses MD5** (`hashlib.md5`, suppressed via `# noqa: S324`). This is not for security — just deterministic hashing for visual identity. Do not replace with a slow hash.
- **Clone does not copy the source agent's `color`**. The clone gets a new auto-generated color from its own UUID.

## Recent Changes

- `2026-03-17` — Initial CLAUDE.md created
