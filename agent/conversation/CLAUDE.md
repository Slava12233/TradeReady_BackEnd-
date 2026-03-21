# agent/conversation/ — Session Management, History, Context, and Intent Routing

<!-- last-updated: 2026-03-21 -->

> Manages the full lifecycle of a conversation between a user and the trading agent: session creation, message persistence, context assembly, rolling summarisation, history retrieval, and intent-based routing.

## What This Module Does

The `agent/conversation/` package is the interaction layer between the agent's LLM reasoning core and the platform database. It provides:

- **Session management** (`AgentSession`) — creates or resumes DB-backed conversation sessions, persists every message, builds token-budgeted context windows, auto-summarises when message counts grow large, and closes sessions with a final summary.
- **History access** (`ConversationHistory`) — load, paginate, and keyword-search messages from closed or active sessions without exposing SQLAlchemy ORM objects to callers.
- **Context assembly** (`ContextBuilder`) — combines six prioritised data sources (system prompt, portfolio state, active strategy, permissions, memory learnings, and conversation history) into a single `list[dict]` for an LLM chat API call.
- **Intent routing** (`IntentRouter`, `IntentType`) — classifies user messages into typed intents using slash commands, regex patterns, and keyword sets (no LLM call required), then dispatches to registered async handler functions.

## Key Files

| File | Purpose |
|------|---------|
| `session.py` | `AgentSession` — full conversation session lifecycle; DB persistence via repository pattern |
| `history.py` | `ConversationHistory` — read-only message loader; `Message` dataclass |
| `context.py` | `ContextBuilder` — assembles multi-source LLM context with token budgeting |
| `router.py` | `IntentRouter`, `IntentType` — slash/regex/keyword message classification and dispatch |
| `__init__.py` | Re-exports `AgentSession`, `SessionError`, `IntentRouter`, `IntentType` |

## Public API

### `AgentSession` (`session.py`)

```python
from agent.conversation import AgentSession, SessionError

session = AgentSession(
    agent_id="550e8400-...",
    session_factory=my_async_sessionmaker,
)
await session.start()
await session.add_message("user", "Analyse BTC for me.")
context = await session.get_context()   # list[dict] ready for LLM
await session.end()
```

**Constructor parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | `str \| UUID` | yes | UUID of the owning agent |
| `session_factory` | `async_sessionmaker[AsyncSession]` | preferred | New DB session per write operation |
| `session_id` | `str \| UUID \| None` | no | Resume a specific existing session |
| `title` | `str \| None` | no | Short title for management UIs |
| `config` | `AgentConfig \| None` | no | Provides `context_max_tokens`, `context_recent_messages`, `context_summary_threshold` |
| `session_repo` | `AgentSessionRepository` | no | Inject mock for testing |
| `message_repo` | `AgentMessageRepository` | no | Inject mock for testing |

**Properties:** `session_id` (UUID | None), `is_active` (bool), `total_tokens` (int)

**Lifecycle methods:**

| Method | Description |
|--------|-------------|
| `start()` | Find/resume active session or create a new one; sets `is_active = True` |
| `add_message(role, content, tool_calls=None, tool_results=None, tokens_used=None)` | Persist message; auto-triggers `summarize_and_trim()` at `context_summary_threshold` |
| `get_context(max_tokens=None)` | Return oldest-first `list[{"role", "content"}]` within token budget |
| `summarize_and_trim()` | LLM-compress older messages into a single `system` summary; fallback to truncated text |
| `end()` | Generate closing summary; mark session `is_active = False` |

**Token estimation:** 1 token ≈ 4 characters (rough estimate for budget enforcement only).

**Summarisation:** `_generate_summary()` calls OpenRouter via `httpx` using `OPENROUTER_API_KEY` env var. Falls back to plain text truncation if the env var is missing or the call fails.

---

### `ConversationHistory` (`history.py`)

```python
from agent.conversation.history import ConversationHistory, Message

history = ConversationHistory(session_factory=my_factory)
messages = await history.load_session("session-uuid")
recent   = await history.load_recent("agent-uuid", limit=30)
matches  = await history.search("agent-uuid", "BTC drawdown")
summary  = await history.get_summary("session-uuid")
```

**`Message` dataclass (frozen):**

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | UUID string of the message |
| `session_id` | `str` | UUID string of the parent session |
| `role` | `str` | `"user"`, `"assistant"`, `"system"`, or `"tool"` |
| `content` | `str` | Plain-text message body |
| `tokens_used` | `int \| None` | Token count, or `None` if not recorded |
| `created_at` | `datetime` | UTC timestamp |

**Methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `load_session(session_id, limit=200, offset=0)` | `list[Message]` | Load messages for one session (oldest first, paginatable) |
| `load_recent(agent_id, limit=50)` | `list[Message]` | Most recent messages across all sessions for an agent (oldest first) |
| `search(agent_id, query, limit=20)` | `list[Message]` | Case-insensitive keyword search; messages that start with the query rank first |
| `get_summary(session_id)` | `str \| None` | Closing LLM summary for a session, or `None` if none exists |

All methods return empty results on any error (never raise).

---

### `ContextBuilder` (`context.py`)

```python
from agent.conversation.context import ContextBuilder

builder = ContextBuilder(config=AgentConfig(), memory_store=store)
messages = await builder.build(agent_id="...", session=session)
```

**Constructor:** `ContextBuilder(config, *, memory_store=None, platform_api_key=None)`

**`build(agent_id, session, max_tokens=None) -> list[dict[str, Any]]`**

Assembles context from six sections in priority order (highest first):

1. **Base system prompt** — `SYSTEM_PROMPT` constant + optional `docs/skill.md` appended (capped at 4000 chars)
2. **Portfolio state** — live balance and 7-day performance via `AsyncAgentExchangeClient`
3. **Active strategy** — first deployed strategy from `GET /api/v1/strategies`
4. **Permissions and budget** — config-derived role, limits, and thresholds (no network call)
5. **Recent learnings** — up to `config.memory_search_limit` memories from `MemoryStore` (PROCEDURAL → SEMANTIC → EPISODIC order)
6. **Conversation messages** — tail of `session.get_context()` with remaining token budget

Each section degrades gracefully — if a source is unavailable the section is simply omitted. The assembled context never raises.

---

### `IntentRouter` and `IntentType` (`router.py`)

```python
from agent.conversation import IntentRouter, IntentType

router = IntentRouter()
router.register(IntentType.TRADE, my_trade_handler)
intent, handler = router.route("show my portfolio balance")
result = await handler(session, "show my portfolio balance")
```

**`IntentType` enum values (str):**

| Value | Triggered by |
|-------|-------------|
| `TRADE` | buy/sell verbs, `place_market_order`, `/trade`, `/buy`, `/sell` |
| `ANALYZE` | analysis/chart/indicator terms, `/analyze` |
| `PORTFOLIO` | balance/positions/P&L/equity terms, `/portfolio` |
| `JOURNAL` | journal/diary/log/note terms, `/journal` |
| `LEARN` | what-is/how-does/explain/tutorial terms, `/learn`, `/help` |
| `PERMISSIONS` | permission/role/access/limits terms, `/permissions` |
| `STATUS` | status/health/ping/uptime terms, `/status`, `/ping` |
| `GENERAL` | fallback when no other pattern matches |

**Classification priority:**
1. Slash commands (`/command`) — always win
2. Compiled regex rules — checked in declaration order, first match wins
3. Keyword token sets — token-level membership test
4. `GENERAL` fallback

**`IntentRouter` methods:**

| Method | Description |
|--------|-------------|
| `register(intent, handler)` | Register/replace an async handler; signature: `async def(session, message, **kwargs) -> str` |
| `classify(message) -> IntentType` | Classify a message; never raises |
| `get_handler(intent) -> HandlerFn` | Return the registered handler; falls back to GENERAL handler |
| `route(message) -> (IntentType, HandlerFn)` | Combined classify + get_handler |

Default handlers are no-op stubs that return an acknowledgement string. Register real handlers before routing.

## Dependency Direction

```
agent.conversation
    │
    ├── src.database.repositories.agent_session_repo
    ├── src.database.repositories.agent_message_repo
    ├── src.database.models (AgentSession, AgentMessage)
    ├── agent.prompts.system (SYSTEM_PROMPT)
    ├── agent.prompts.skill_context (load_skill_context)
    └── agent.memory.store (MemoryType — in ContextBuilder only)
```

All `src.database` imports are lazy (inside methods) to keep the module importable in test environments without a running database.

## Patterns

- **Dual injection mode**: `AgentSession` and `ConversationHistory` accept either a `session_factory` (production) or pre-built repo instances (test mocks). Use repos in tests; factory in production.
- **Short-lived DB sessions**: Every write in `AgentSession` opens, commits, and closes its own `AsyncSession` immediately. No long-lived transactions.
- **Token estimation is approximate**: All token counts use the `_CHARS_PER_TOKEN = 4` heuristic. This is sufficient for budget enforcement but do not rely on it for exact billing.
- **Lazy imports throughout**: All `src.*` imports are inside method bodies (`# noqa: PLC0415`) to avoid circular imports at module load time.

## Gotchas

- **`start()` must be called before `add_message()` or `get_context()`**. Both raise `SessionError` if the session has not been started.
- **Summarisation failure is non-fatal**. `add_message()` catches all errors from `summarize_and_trim()` and logs a warning rather than propagating. A message persist failure does raise `SessionError`.
- **Auto-summarisation fires at `context_summary_threshold` messages** (default 50). After summarisation, older messages are deleted from the DB. The summary is written as a `system` role message.
- **`ConversationHistory.search()` is O(sessions × messages)**. It fetches session IDs first, then up to 500 messages per session. Efficient for ≤ 100 sessions; avoid for very large histories.
- **`ContextBuilder` caches nothing**. Every `build()` call makes fresh network calls for portfolio and strategy data. Use it once per LLM invocation, not in a hot loop.
- **The `IntentRouter` is not thread-safe for `register()` after first use**. The `_action_map` in `PermissionEnforcer.require()` temporarily mutates the router; avoid calling `register()` concurrently.
