"""Persistent agent server process with async event loop.

Provides :class:`AgentServer` — a long-running process that wraps the
Pydantic AI agent with full lifecycle management: startup (DB session + Redis
+ memory system), message processing, scheduled tasks, health reporting, and
graceful shutdown.

This module replaces the one-shot CLI pattern from ``agent/main.py`` with a
persistent server that can handle many sequential conversations without
re-initialising its dependencies on each request.

Usage::

    import asyncio
    import signal
    from agent.config import AgentConfig
    from agent.server import AgentServer

    config = AgentConfig()
    server = AgentServer(agent_id="your-agent-uuid", config=config)

    # Run until SIGINT / SIGTERM
    asyncio.run(server.start())

Signal handling is built-in: ``SIGINT`` and ``SIGTERM`` both trigger
:meth:`AgentServer.stop`, which performs a clean shutdown.

The server never raises from :meth:`start` unless initial setup fails fatally
(e.g. required env vars missing).  All per-message and per-task errors are
caught internally and logged.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import UTC, datetime
from typing import Any

import structlog

from agent.config import AgentConfig
from agent.conversation.router import IntentRouter, IntentType
from agent.conversation.session import AgentSession, SessionError
from agent.logging import set_agent_id
from agent.logging_writer import LogBatchWriter
from agent.memory.redis_cache import RedisMemoryCache
from agent.memory.store import Memory, MemoryStore
from agent.server_handlers import (
    REASONING_LOOP_SENTINEL,
    handle_analyze,
    handle_general,
    handle_journal,
    handle_learn,
    handle_permissions,
    handle_portfolio,
    handle_status,
    handle_trade,
)
from agent.trading.ws_manager import WSManager

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Sentinel value used as the auto-restart sleep interval (seconds).
# ---------------------------------------------------------------------------
_RESTART_SLEEP: float = 5.0

# Maximum number of consecutive processing errors before the server backs off.
_MAX_CONSECUTIVE_ERRORS: int = 10


class AgentServerError(Exception):
    """Raised for unrecoverable errors during AgentServer initialisation.

    Args:
        message: Human-readable description of the failure.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AgentServer:
    """Persistent agent process with async event loop.

    Manages the full server lifecycle:

    * **Startup** — opens a DB session factory, connects to Redis, and
      initialises the memory system (PostgresMemoryStore + RedisMemoryCache).
    * **Message processing** — feeds each user message through the Pydantic AI
      agent, persists the exchange via :class:`~agent.conversation.AgentSession`,
      and optionally saves learned facts to the memory store.
    * **Scheduled tasks** — runs a periodic ``morning_review`` task at the
      configured UTC hour and a periodic state-persistence heartbeat.
    * **Health reporting** — :meth:`health_check` returns uptime, current
      session ID, last-activity timestamp, and memory statistics.
    * **Graceful shutdown** — :meth:`stop` signals the event loop to drain,
      persists working state to Redis, and closes all open connections.
    * **Auto-restart** — the reasoning loop wraps each iteration in
      ``try/except`` so transient errors (network timeouts, LLM failures)
      never bring the server down; it backs off for
      :data:`_RESTART_SLEEP` seconds and resumes.

    Signal handling (``SIGINT`` / ``SIGTERM``) is installed in
    :meth:`start` and removed in :meth:`stop`.

    Args:
        agent_id: UUID string of the trading agent that owns this server
            process.  Must correspond to a row in the ``agents`` table.
        config: :class:`~agent.config.AgentConfig` instance with all
            connectivity settings resolved from ``agent/.env``.

    Example::

        server = AgentServer(agent_id="550e8400-e29b-41d4-a716-446655440000",
                             config=AgentConfig())
        asyncio.run(server.start())
    """

    def __init__(self, agent_id: str, config: AgentConfig) -> None:
        self._agent_id = agent_id
        self._config = config

        # Initialised during start()
        self._session: AgentSession | None = None
        self._memory_store: MemoryStore | None = None
        self._redis_cache: RedisMemoryCache | None = None
        self._pydantic_agent: Any = None  # pydantic_ai.Agent
        self._batch_writer: LogBatchWriter | None = None
        self._ws_manager: WSManager | None = None

        # Lifecycle state
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._started_at: datetime | None = None
        self._last_activity: datetime | None = None
        self._is_running: bool = False
        self._consecutive_errors: int = 0

        self._log = logger.bind(agent_id=agent_id)

        # Bind agent_id into the asyncio context so every log line on this
        # context automatically carries the agent_id correlation field via the
        # add_correlation_context processor in agent.logging.
        set_agent_id(agent_id)

        # Build and wire the intent router with concrete handlers.
        # Each handler is a standalone async function from server_handlers.py
        # that calls real SDK / tool methods.  The GENERAL handler returns a
        # sentinel which process_message() replaces with the LLM response.
        self._router: IntentRouter = IntentRouter()
        self._router.register(IntentType.TRADE, handle_trade)
        self._router.register(IntentType.ANALYZE, handle_analyze)
        self._router.register(IntentType.PORTFOLIO, handle_portfolio)
        self._router.register(IntentType.STATUS, handle_status)
        self._router.register(IntentType.JOURNAL, handle_journal)
        self._router.register(IntentType.LEARN, handle_learn)
        self._router.register(IntentType.PERMISSIONS, handle_permissions)
        self._router.register(IntentType.GENERAL, handle_general)
        self._log.info("agent_server.router_ready", intents=len(IntentType))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def batch_writer(self) -> LogBatchWriter | None:
        """The active :class:`~agent.logging_writer.LogBatchWriter`, or ``None``.

        ``None`` before :meth:`_init_dependencies` is called (i.e. before
        :meth:`start`) or when the DB is unavailable.
        """
        return self._batch_writer

    @property
    def ws_manager(self) -> WSManager | None:
        """The active :class:`~agent.trading.ws_manager.WSManager`, or ``None``.

        ``None`` before :meth:`start` completes or when WebSocket is disabled
        (missing ``PLATFORM_API_KEY`` or init failure).  Available after
        :meth:`_init_ws_manager` succeeds; pass it to a :class:`~agent.trading.loop.TradingLoop`
        so the loop reads prices from the buffer instead of polling REST.
        """
        return self._ws_manager

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the persistent agent server and block until shutdown.

        Performs the following in order:

        1. Install ``SIGINT`` / ``SIGTERM`` handlers.
        2. Initialise the DB session factory, Redis client, and memory system.
        3. Start (or resume) the agent conversation session.
        4. Build the Pydantic AI agent with platform tools.
        5. Launch background tasks (health-check loop, scheduled tasks loop).
        6. Block on :attr:`_shutdown_event`.
        7. On shutdown: persist state, end the session, close connections.

        Raises:
            AgentServerError: If any mandatory initialisation step fails
                (e.g. DB unreachable, missing API key).
        """
        self._install_signal_handlers()
        self._started_at = datetime.now(UTC)
        self._is_running = True
        self._log.info("agent_server.starting", host=self._config.agent_server_host,
                       port=self._config.agent_server_port)

        try:
            await self._init_dependencies()
            await self._init_session()
            await self._init_pydantic_agent()
            await self._init_ws_manager()
        except Exception as exc:
            self._log.exception("agent_server.init_failed", error=str(exc))
            raise AgentServerError(f"Server initialisation failed: {exc}") from exc

        self._log.info("agent_server.ready", agent_id=self._agent_id)

        # Launch background loops as tasks
        background_tasks = [
            asyncio.create_task(self._health_check_loop(), name="health_check_loop"),
            asyncio.create_task(self._scheduled_task_loop(), name="scheduled_task_loop"),
            asyncio.create_task(self._metrics_server_loop(), name="metrics_server_loop"),
        ]

        try:
            # Block until a shutdown signal is received
            await self._shutdown_event.wait()
        finally:
            self._log.info("agent_server.shutdown_initiated")

            # Cancel background tasks gracefully
            for task in background_tasks:
                task.cancel()
            await asyncio.gather(*background_tasks, return_exceptions=True)

            await self._shutdown()

    async def stop(self) -> None:
        """Signal the server to shut down cleanly.

        Can be called from anywhere (signal handler, external orchestrator,
        or test harness).  Sets :attr:`_shutdown_event` which unblocks
        :meth:`start`.

        Safe to call multiple times — subsequent calls are no-ops.
        """
        if not self._shutdown_event.is_set():
            self._log.info("agent_server.stop_requested")
            self._shutdown_event.set()

    async def process_message(self, message: str, session: AgentSession) -> str:
        """Process a user message through the Pydantic AI agent.

        Adds the user message to the session, runs the LLM reasoning loop,
        persists the assistant reply, and returns the reply text.

        The method never raises — any unhandled exception is caught, logged,
        and returned to the caller as an error message string.

        Args:
            message: The raw user message text.
            session: An already-started :class:`~agent.conversation.AgentSession`
                for the current conversation.  Messages are persisted here.

        Returns:
            The assistant's reply as a plain string.  On error, a
            human-friendly error description is returned instead.
        """
        self._last_activity = datetime.now(UTC)

        try:
            await session.add_message("user", message)
        except SessionError as exc:
            self._log.warning("process_message.persist_user_failed", error=str(exc))

        try:
            context = await session.get_context()

            # Route the message through the IntentRouter first.  Handlers for
            # TRADE, ANALYZE, PORTFOLIO, STATUS, JOURNAL, LEARN, and PERMISSIONS
            # produce direct replies without invoking the LLM.  The GENERAL
            # handler returns REASONING_LOOP_SENTINEL to signal that the full
            # Pydantic AI reasoning loop should handle this message instead.
            intent, handler = self._router.route(message)
            self._log.info(
                "agent.server.routing",
                intent=intent.value,
                message_preview=message[:80],
            )
            handler_reply = await handler(
                session,
                message,
                server=self,
                memory_store=self._memory_store,
            )

            if handler_reply == REASONING_LOOP_SENTINEL:
                reply = await self._reasoning_loop(context, message)
            else:
                reply = handler_reply

        except Exception as exc:  # noqa: BLE001 — broad catch is intentional here
            self._log.exception("process_message.reasoning_failed", error=str(exc))
            self._consecutive_errors += 1
            reply = (
                f"I encountered an error while processing your request. "
                f"Please try again. (detail: {exc})"
            )
        else:
            self._consecutive_errors = 0

        try:
            await session.add_message("assistant", reply)
        except SessionError as exc:
            self._log.warning("process_message.persist_assistant_failed", error=str(exc))

        return reply

    async def health_check(self) -> dict[str, Any]:
        """Return a snapshot of the server's current health.

        Checks Redis connectivity and reports session and memory statistics.
        Safe to call at any time after :meth:`start`; returns a minimal dict
        before startup completes.

        Returns:
            A dict with the following keys:

            * ``status`` — ``"healthy"`` / ``"degraded"`` / ``"starting"``
            * ``uptime_seconds`` — elapsed seconds since :meth:`start` was
              called (``null`` before startup).
            * ``agent_id`` — the agent UUID string.
            * ``active_session_id`` — current session UUID string or
              ``null`` if no session is open.
            * ``last_activity`` — ISO-8601 timestamp of the most recent
              :meth:`process_message` call, or ``null``.
            * ``consecutive_errors`` — number of unhandled errors since the
              last successful message processing.
            * ``redis_ok`` — boolean; ``True`` if Redis responded to a ping.
            * ``memory_stats`` — sub-dict with ``recent_memory_count``.
        """
        if not self._is_running:
            return {"status": "starting", "agent_id": self._agent_id}

        uptime: float | None = None
        if self._started_at is not None:
            uptime = (datetime.now(UTC) - self._started_at).total_seconds()

        session_id: str | None = None
        if self._session is not None and self._session.session_id is not None:
            session_id = str(self._session.session_id)

        redis_ok = await self._ping_redis()
        memory_stats = await self._collect_memory_stats()

        status = "healthy"
        if not redis_ok or self._consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
            status = "degraded"

        return {
            "status": status,
            "uptime_seconds": uptime,
            "agent_id": self._agent_id,
            "active_session_id": session_id,
            "last_activity": self._last_activity.isoformat() if self._last_activity else None,
            "consecutive_errors": self._consecutive_errors,
            "redis_ok": redis_ok,
            "memory_stats": memory_stats,
        }

    async def run_scheduled_task(self, task_name: str) -> None:
        """Execute a named scheduled task.

        Supported task names:

        * ``"morning_review"`` — fetches recent memories and market context,
          produces a brief LLM commentary, and persists it as a system message
          in the active session.
        * ``"persist_state"`` — calls :meth:`_persist_state` to write working
          memory to Redis.

        Unrecognised task names are logged as warnings and ignored.

        Args:
            task_name: The name of the task to run.
        """
        self._log.info("scheduled_task.start", task=task_name)
        try:
            if task_name == "morning_review":
                await self._run_morning_review()
            elif task_name == "persist_state":
                await self._persist_state()
            else:
                self._log.warning("scheduled_task.unknown", task=task_name)
        except Exception as exc:  # noqa: BLE001
            self._log.exception("scheduled_task.failed", task=task_name, error=str(exc))

    # ------------------------------------------------------------------
    # Internal initialisation
    # ------------------------------------------------------------------

    async def _init_dependencies(self) -> None:
        """Open DB session factory, Redis client, and memory layer.

        Sets ``self._memory_store`` and ``self._redis_cache``.

        Raises:
            AgentServerError: If the DB engine cannot be created.
        """
        self._log.info("agent_server.init_dependencies")

        # Redis hot cache — lazy connection; errors surface on first real use
        self._redis_cache = RedisMemoryCache(config=self._config)

        # Postgres memory store — requires a DB session factory
        try:
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: PLC0415
            from src.config import get_settings  # noqa: PLC0415
            from src.database.repositories.agent_learning_repo import (  # noqa: PLC0415
                AgentLearningRepository,
            )

            from agent.memory.postgres_store import PostgresMemoryStore  # noqa: PLC0415

            settings = get_settings()
            engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
            self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

            # Instantiate a short-lived DB session to verify connectivity
            async with self._session_factory() as db_session:
                repo = AgentLearningRepository(db_session)
                self._memory_store = PostgresMemoryStore(repo=repo, config=self._config)
                # Close and discard this session; _memory_store is stateless
                # (it only uses the repo passed at construction for the first op;
                # subsequent callers pass fresh repos as needed).

            # Create and start the batch writer for async DB logging
            self._batch_writer = LogBatchWriter(session_factory=self._session_factory)
            await self._batch_writer.start()

            self._log.info("agent_server.db_connected")
        except Exception as exc:
            # DB is optional for memory — degrade gracefully
            self._log.warning("agent_server.db_unavailable", error=str(exc))
            self._memory_store = None
            self._session_factory = None  # type: ignore[assignment]
            self._batch_writer = None

    async def _init_session(self) -> None:
        """Create or resume the conversation session for this agent.

        Sets ``self._session`` and calls :meth:`AgentSession.start`.
        Falls back to a sessionless mode if the DB is unavailable.
        """
        self._log.info("agent_server.init_session")

        if self._session_factory is None:
            self._log.warning("agent_server.session_skipped_no_db")
            self._session = None
            return

        try:
            self._session = AgentSession(
                agent_id=self._agent_id,
                session_factory=self._session_factory,
                config=self._config,
            )
            await self._session.start()
            self._log.info(
                "agent_server.session_ready",
                session_id=str(self._session.session_id),
            )
        except SessionError as exc:
            self._log.warning("agent_server.session_start_failed", error=str(exc))
            self._session = None

    async def _init_pydantic_agent(self) -> None:
        """Build the Pydantic AI :class:`~pydantic_ai.Agent` with SDK tools.

        Uses ``config.agent_model`` as the LLM.  SDK tools from
        :func:`~agent.tools.sdk_tools.get_sdk_tools` are registered if
        ``platform_api_key`` is set; otherwise the agent runs with no tools
        (useful for smoke testing without a live platform).
        """
        self._log.info("agent_server.init_pydantic_agent", model=self._config.agent_model)

        try:
            import os  # noqa: PLC0415

            from pydantic_ai import Agent  # noqa: PLC0415

            from agent.prompts.system import SYSTEM_PROMPT  # noqa: PLC0415
            from agent.tools.sdk_tools import get_sdk_tools  # noqa: PLC0415

            # Pydantic AI's OpenRouterProvider reads the API key from the OS
            # environment, but AgentConfig loads it from agent/.env via
            # pydantic-settings. Bridge the gap by injecting the key into the
            # process environment before the provider is instantiated.
            if self._config.openrouter_api_key and not os.environ.get("OPENROUTER_API_KEY"):
                os.environ["OPENROUTER_API_KEY"] = self._config.openrouter_api_key

            tools: list[Any] = []
            if self._config.platform_api_key:
                tools = get_sdk_tools(self._config)

            self._pydantic_agent = Agent(
                model=self._config.agent_model,
                system_prompt=SYSTEM_PROMPT,
                tools=tools,
            )
            self._log.info("agent_server.pydantic_agent_ready", tools=len(tools))
        except Exception as exc:
            self._log.exception("agent_server.pydantic_agent_init_failed", error=str(exc))
            self._pydantic_agent = None

    async def _init_ws_manager(self) -> None:
        """Connect the WebSocket manager for real-time price and order streaming.

        Creates a :class:`~agent.trading.ws_manager.WSManager`, subscribes to
        ticker channels for every configured symbol and to the ``orders``
        channel, then starts the WS connection as a background asyncio task.

        If ``platform_api_key`` is empty the WebSocket connection is skipped
        and ``_ws_manager`` remains ``None``; the trading loop will fall back
        to REST polling.

        Errors during WS setup are logged as warnings, not raised, so the
        server can start without a live WebSocket.
        """
        self._log.info(
            "agent_server.init_ws_manager",
            symbols=self._config.symbols,
        )

        if not self._config.platform_api_key:
            self._log.warning(
                "agent_server.ws_manager.skipped",
                reason="PLATFORM_API_KEY is empty — WebSocket disabled.",
            )
            return

        try:
            ws_manager = WSManager(config=self._config)
            await ws_manager.connect()
            self._ws_manager = ws_manager
            self._log.info(
                "agent_server.ws_manager.started",
                symbols=self._config.symbols,
            )
        except Exception as exc:  # noqa: BLE001
            self._log.warning(
                "agent_server.ws_manager.init_failed",
                error=str(exc),
                hint="Continuing without WebSocket — trading loop will use REST polling.",
            )
            self._ws_manager = None

    # ------------------------------------------------------------------
    # Core reasoning loop
    # ------------------------------------------------------------------

    async def _reasoning_loop(
        self, context: list[dict[str, Any]], message: str
    ) -> str:
        """Run the Pydantic AI agent on the current message and return a reply.

        Builds a single user prompt that includes the serialised conversation
        context followed by the new message, then calls
        ``agent.run(prompt)``.

        If the Pydantic AI agent is not available (e.g. missing API key or
        failed initialisation), the method falls back to a deterministic
        echo/acknowledge response that signals the degraded state.

        Args:
            context: List of ``{"role": str, "content": str}`` dicts from
                :meth:`~agent.conversation.AgentSession.get_context`.
            message: The new user message text.

        Returns:
            The LLM reply as a plain string, or a degraded-mode fallback.
        """
        if self._pydantic_agent is None:
            self._log.warning("reasoning_loop.no_agent_fallback")
            return (
                "[Agent unavailable — running in degraded mode.  "
                f"Received: {message[:200]}]"
            )

        # Compose context into a single prompt prefix
        context_text = ""
        if context:
            lines: list[str] = []
            for msg in context:
                role = str(msg.get("role", "unknown")).upper()
                content = str(msg.get("content", ""))[:500]
                lines.append(f"[{role}]: {content}")
            context_text = "Conversation history:\n" + "\n".join(lines) + "\n\n"

        full_prompt = f"{context_text}User: {message}"

        try:
            result = await self._pydantic_agent.run(full_prompt)
            reply: str = str(result.output) if result.output is not None else ""
            self._log.info(
                "reasoning_loop.success",
                prompt_len=len(full_prompt),
                reply_len=len(reply),
            )
            return reply
        except Exception as exc:
            self._log.exception("reasoning_loop.llm_error", error=str(exc))
            raise

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    async def _persist_state(self) -> None:
        """Flush current working state to Redis.

        Writes the following keys to the agent's working memory hash:

        * ``last_activity`` — ISO-8601 timestamp.
        * ``uptime_seconds`` — elapsed seconds since start.
        * ``consecutive_errors`` — current error counter.
        * ``session_id`` — active conversation session UUID (if any).

        Silently ignores Redis errors (logged at WARNING level by the cache).
        """
        if self._redis_cache is None:
            return

        uptime: float = 0.0
        if self._started_at is not None:
            uptime = (datetime.now(UTC) - self._started_at).total_seconds()

        session_id = ""
        if self._session is not None and self._session.session_id is not None:
            session_id = str(self._session.session_id)

        await self._redis_cache.set_working(self._agent_id, "last_activity",
                                            self._last_activity.isoformat()
                                            if self._last_activity else "")
        await self._redis_cache.set_working(self._agent_id, "uptime_seconds", str(uptime))
        await self._redis_cache.set_working(self._agent_id, "consecutive_errors",
                                            str(self._consecutive_errors))
        await self._redis_cache.set_working(self._agent_id, "session_id", session_id)

        self._log.debug("agent_server.state_persisted")

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------

    async def _metrics_server_loop(self) -> None:
        """Serve Prometheus metrics and a JSON health endpoint on the agent HTTP port.

        Listens on ``config.agent_server_host:config.agent_server_port`` (default
        ``0.0.0.0:8001``).  Responds to:

        - ``GET /metrics`` — Prometheus text exposition format (``AGENT_REGISTRY``
          only; does not expose the platform-default Prometheus registry).
        - ``GET /health`` — JSON health snapshot from :meth:`health_check`.

        All other paths receive a ``404 Not Found`` response.

        The server runs until the shutdown event fires, then stops accepting new
        connections.  Any ``asyncio.CancelledError`` is re-raised so the parent
        task-group can clean up correctly.
        """
        from prometheus_client import generate_latest  # noqa: PLC0415

        from agent.metrics import AGENT_REGISTRY  # noqa: PLC0415

        host = self._config.agent_server_host
        port = self._config.agent_server_port

        async def _handle_connection(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            """Handle one HTTP connection and write a response."""
            import json as _json  # noqa: PLC0415

            try:
                raw = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not raw:
                    return

                # Parse the request line — first line, e.g. "GET /metrics HTTP/1.1".
                first_line = raw.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
                parts = first_line.split(" ")
                path = parts[1] if len(parts) >= 2 else "/"

                if path == "/metrics":
                    body = generate_latest(AGENT_REGISTRY)
                    status = "200 OK"
                    content_type = "text/plain; version=0.0.4; charset=utf-8"
                    response_body = body
                elif path == "/health":
                    health = await self.health_check()
                    response_body = _json.dumps(health).encode("utf-8")
                    status = "200 OK"
                    content_type = "application/json"
                else:
                    response_body = b"Not Found\n"
                    status = "404 Not Found"
                    content_type = "text/plain"

                headers = (
                    f"HTTP/1.1 {status}\r\n"
                    f"Content-Type: {content_type}\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    f"Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("utf-8"))
                writer.write(response_body)
                await writer.drain()
            except (TimeoutError, asyncio.IncompleteReadError, ConnectionResetError):
                pass
            except Exception as exc:  # noqa: BLE001
                self._log.debug("metrics_server.handler_error", error=str(exc))
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:  # noqa: BLE001
                    pass

        try:
            tcp_server = await asyncio.start_server(
                _handle_connection, host=host, port=port
            )
            self._log.info(
                "agent_server.metrics_server.started",
                host=host,
                port=port,
                paths=["/metrics", "/health"],
            )
            async with tcp_server:
                await self._shutdown_event.wait()

        except asyncio.CancelledError:
            self._log.info("metrics_server.cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            self._log.warning(
                "agent_server.metrics_server.failed",
                host=host,
                port=port,
                error=str(exc),
            )

    async def _health_check_loop(self) -> None:
        """Run a periodic health-check and state-persistence cycle.

        Fires every ``config.agent_health_check_interval`` seconds.  On each
        tick it calls :meth:`_persist_state` and logs the health snapshot at
        ``DEBUG`` level.  Cancellation (from :meth:`stop`) exits cleanly.
        """
        interval = self._config.agent_health_check_interval
        self._log.info("health_check_loop.started", interval_s=interval)

        try:
            while not self._shutdown_event.is_set():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._shutdown_event.wait()),
                        timeout=float(interval),
                    )
                    # shutdown_event fired within the wait — exit loop
                    break
                except TimeoutError:
                    pass  # Normal path: interval elapsed, run health check

                try:
                    await self._persist_state()
                    health = await self.health_check()
                    self._log.debug("health_check_loop.tick", **health)
                except Exception as exc:  # noqa: BLE001
                    self._log.warning("health_check_loop.error", error=str(exc))
        except asyncio.CancelledError:
            self._log.info("health_check_loop.cancelled")
            raise

    async def _scheduled_task_loop(self) -> None:
        """Check and run time-triggered tasks once per minute.

        Currently schedules ``morning_review`` at the UTC hour configured in
        ``config.agent_scheduled_review_hour``.  The task fires at most once
        per calendar hour by tracking the last run hour.

        Cancellation exits cleanly.
        """
        self._log.info("scheduled_task_loop.started")
        last_review_hour: int = -1  # sentinel — never matches a real hour

        try:
            while not self._shutdown_event.is_set():
                # Check every 60 seconds
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._shutdown_event.wait()),
                        timeout=60.0,
                    )
                    break
                except TimeoutError:
                    pass

                now = datetime.now(UTC)
                if (
                    now.hour == self._config.agent_scheduled_review_hour
                    and now.hour != last_review_hour
                ):
                    last_review_hour = now.hour
                    await self.run_scheduled_task("morning_review")
        except asyncio.CancelledError:
            self._log.info("scheduled_task_loop.cancelled")
            raise

    # ------------------------------------------------------------------
    # Scheduled task implementations
    # ------------------------------------------------------------------

    async def _run_morning_review(self) -> None:
        """Fetch recent memories and inject a brief LLM market briefing.

        Retrieves the most recent procedural and semantic memories for the
        agent, then asks the Pydantic AI agent to summarise them as a morning
        briefing.  The result is persisted as a ``system`` message in the
        active session.

        Does nothing if no session or memory store is available.
        """
        self._log.info("morning_review.start")

        if self._session is None or not self._session.is_active:
            self._log.info("morning_review.skipped_no_session")
            return

        memories: list[Memory] = []
        if self._memory_store is not None:
            try:
                memories = await self._memory_store.get_recent(
                    agent_id=self._agent_id,
                    limit=self._config.memory_search_limit,
                )
            except Exception as exc:  # noqa: BLE001
                self._log.warning("morning_review.memory_fetch_failed", error=str(exc))

        if not memories:
            briefing = (
                "Morning review: no prior learnings recorded.  "
                "Starting fresh today."
            )
        else:
            memory_lines = [
                f"- [{m.memory_type.value}] {m.content[:200]}"
                for m in memories[:10]
            ]
            briefing_prompt = (
                "You are producing a brief morning review for a trading agent.  "
                "Based on the following recorded learnings, write a concise "
                "(3-5 sentence) briefing covering the most important things "
                "the agent should keep in mind today.\n\n"
                "LEARNINGS:\n" + "\n".join(memory_lines)
            )

            if self._pydantic_agent is not None:
                try:
                    result = await self._pydantic_agent.run(briefing_prompt)
                    briefing = str(result.output) if result.output else "(no review generated)"
                except Exception as exc:  # noqa: BLE001
                    self._log.warning("morning_review.llm_failed", error=str(exc))
                    briefing = "\n".join(memory_lines)
            else:
                briefing = "\n".join(memory_lines)

        try:
            await self._session.add_message("system", f"[MORNING REVIEW]\n{briefing}")
            self._log.info("morning_review.complete", briefing_len=len(briefing))
        except SessionError as exc:
            self._log.warning("morning_review.persist_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Health helpers
    # ------------------------------------------------------------------

    async def _ping_redis(self) -> bool:
        """Return ``True`` if Redis responds to a ping within 2 seconds.

        Returns:
            ``True`` on success; ``False`` on any error or timeout.
        """
        if self._redis_cache is None:
            return False
        try:

            redis = await self._redis_cache._get_redis()
            await asyncio.wait_for(redis.ping(), timeout=2.0)
            return True
        except (TimeoutError, Exception):  # noqa: BLE001
            return False

    async def _collect_memory_stats(self) -> dict[str, Any]:
        """Return a dict of memory layer statistics.

        Returns:
            Dict with ``recent_memory_count`` (int).  Returns zeros if the
            memory store is unavailable.
        """
        recent_count = 0
        if self._memory_store is not None:
            try:
                recent = await self._memory_store.get_recent(
                    agent_id=self._agent_id, limit=100
                )
                recent_count = len(recent)
            except Exception:  # noqa: BLE001
                pass

        return {"recent_memory_count": recent_count}

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def _shutdown(self) -> None:
        """Perform graceful shutdown: persist state, end session, close connections.

        Called automatically from :meth:`start` after the shutdown event is
        set.  Never raises — all errors are caught and logged.
        """
        self._log.info("agent_server.shutdown_start")
        self._is_running = False

        # Drain and stop the batch writer before closing the DB session factory
        if self._batch_writer is not None:
            try:
                await self._batch_writer.stop()
            except Exception as exc:  # noqa: BLE001
                self._log.warning("agent_server.shutdown_writer_stop_failed", error=str(exc))

        # Persist current working state
        try:
            await self._persist_state()
        except Exception as exc:  # noqa: BLE001
            self._log.warning("agent_server.shutdown_persist_failed", error=str(exc))

        # Clear working memory from Redis (session is ending cleanly)
        if self._redis_cache is not None:
            try:
                await self._redis_cache.clear_working(self._agent_id)
            except Exception as exc:  # noqa: BLE001
                self._log.warning("agent_server.shutdown_clear_working_failed", error=str(exc))

        # Disconnect the WebSocket manager before closing the session so that
        # any in-flight fill notifications are drained cleanly.
        if self._ws_manager is not None:
            try:
                await self._ws_manager.disconnect()
            except Exception as exc:  # noqa: BLE001
                self._log.warning("agent_server.shutdown_ws_disconnect_failed", error=str(exc))
            self._ws_manager = None

        # End the conversation session
        if self._session is not None and self._session.is_active:
            try:
                await self._session.end()
            except SessionError as exc:
                self._log.warning("agent_server.shutdown_session_end_failed", error=str(exc))

        self._log.info("agent_server.shutdown_complete")

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Register SIGINT and SIGTERM handlers to trigger graceful shutdown.

        Uses :func:`asyncio.get_event_loop` so the handlers run in the
        context of the running event loop.  On Windows, only ``SIGINT`` is
        supported; ``SIGTERM`` is skipped silently.
        """
        loop = asyncio.get_event_loop()

        def _handle_signal(sig: signal.Signals) -> None:  # type: ignore[name-defined]
            self._log.info("agent_server.signal_received", signal=sig.name)
            loop.call_soon_threadsafe(self._shutdown_event.set)

        try:
            loop.add_signal_handler(signal.SIGINT, _handle_signal, signal.SIGINT)
        except (NotImplementedError, ValueError):
            # Fallback for platforms (e.g. Windows) that do not support
            # add_signal_handler — rely on KeyboardInterrupt instead.
            self._log.debug("agent_server.sigint_handler_skipped")

        try:
            loop.add_signal_handler(signal.SIGTERM, _handle_signal, signal.SIGTERM)
        except (NotImplementedError, ValueError):
            self._log.debug("agent_server.sigterm_handler_skipped")


# ---------------------------------------------------------------------------
# Module-level entry point for ``python -m agent.server``
# ---------------------------------------------------------------------------


async def _run_server(agent_id: str | None = None) -> None:
    """Bootstrap and run an :class:`AgentServer` from the command line.

    Reads configuration from ``agent/.env`` via :class:`~agent.config.AgentConfig`.
    The ``AGENT_ID`` environment variable (or first CLI argument) specifies
    which agent to serve.

    Args:
        agent_id: Override the agent ID.  When ``None``, falls back to the
            ``AGENT_ID`` environment variable, then to a placeholder UUID
            for local development.
    """
    import os  # noqa: PLC0415

    try:
        config = AgentConfig()
    except Exception as exc:  # noqa: BLE001
        print(  # noqa: T201
            f"ERROR: Failed to load AgentConfig from agent/.env\n  {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    effective_agent_id = (
        agent_id
        or os.environ.get("AGENT_ID", "")
        or "00000000-0000-0000-0000-000000000001"
    )

    server = AgentServer(agent_id=effective_agent_id, config=config)
    try:
        await server.start()
    except AgentServerError as exc:
        print(  # noqa: T201
            f"ERROR: Agent server failed to start: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    _agent_id_arg: str | None = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(_run_server(_agent_id_arg))
