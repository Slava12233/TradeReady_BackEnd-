"""Interactive CLI REPL for chatting with the TradeReady agent.

Provides :func:`run_chat` — an interactive read-eval-print loop that
connects a terminal user to the agent's conversation and intent-routing
system.

The REPL:

* Resumes or creates an :class:`~agent.conversation.AgentSession` (backed by
  the DB when available; falls back to in-memory-only mode if the DB is
  unreachable so the CLI still works for a quick chat).
* Classifies each message with :class:`~agent.conversation.IntentRouter` and
  dispatches it to the appropriate intent handler **or** falls through to the
  :class:`~agent.server.AgentServer` reasoning loop for natural-language
  queries.
* Processes slash commands locally (``/help``, ``/quit``, ``/session``, etc.)
  without touching the LLM, keeping latency near-zero for control operations.
* Uses ``rich`` for formatted terminal output when available; degrades to plain
  ``print()`` when ``rich`` is not installed.

Slash commands
--------------
+------------------------------+------------------------------------------+
| Command                      | Description                              |
+==============================+==========================================+
| ``/help``                    | Show available commands                  |
+------------------------------+------------------------------------------+
| ``/trade [symbol] [dir]``    | Initiate trade discussion                |
+------------------------------+------------------------------------------+
| ``/analyze [symbol]``        | Analyse a specific market                |
+------------------------------+------------------------------------------+
| ``/portfolio``               | Show portfolio summary                   |
+------------------------------+------------------------------------------+
| ``/journal [entry]``         | Write or read journal                    |
+------------------------------+------------------------------------------+
| ``/learn``                   | Show recent learnings                    |
+------------------------------+------------------------------------------+
| ``/permissions``             | Show current permissions                 |
+------------------------------+------------------------------------------+
| ``/status``                  | Agent health and stats                   |
+------------------------------+------------------------------------------+
| ``/session [new|list|ID]``   | Session management                       |
+------------------------------+------------------------------------------+
| ``/quit`` / ``/exit``        | Exit the REPL                            |
+------------------------------+------------------------------------------+

Usage::

    python -m agent chat
    python -m agent chat --agent-id 550e8400-e29b-41d4-a716-446655440000
    python -m agent chat --session-id abc123
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from agent.config import AgentConfig
from agent.conversation.router import IntentRouter
from agent.server import AgentServer

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Rich / plain-text display layer
# ---------------------------------------------------------------------------

# Try to import rich; fall back to plain print if not installed.
try:
    from rich.console import Console as _RichConsole
    from rich.markdown import Markdown as _RichMarkdown
    from rich.panel import Panel as _RichPanel
    from rich.table import Table as _RichTable

    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False

# Version string shown in the welcome banner.
_AGENT_VERSION = "2"

# Placeholder default for agent_id when none is supplied.
_DEFAULT_AGENT_ID = "00000000-0000-0000-0000-000000000001"

# Maximum width (chars) for wrapped plain-text agent replies.
_PLAIN_WRAP_WIDTH = 80


# ---------------------------------------------------------------------------
# TerminalUI — thin abstraction over rich / plain print
# ---------------------------------------------------------------------------


class TerminalUI:
    """Render REPL output using ``rich`` when available, else plain text.

    All display methods are synchronous (no I/O awaiting needed for terminal
    output) and safe to call from within the async REPL loop.

    Args:
        use_rich: Force-override the ``rich`` availability check.  Intended
            for testing; pass ``False`` to always use plain text.
    """

    def __init__(self, use_rich: bool | None = None) -> None:
        if use_rich is None:
            self._rich = _RICH_AVAILABLE
        else:
            self._rich = use_rich

        if self._rich:
            self._console = _RichConsole()

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------

    def print_banner(self, session_id: str | None, is_resumed: bool) -> None:
        """Print the welcome banner with session information.

        Args:
            session_id: Active session UUID string, or ``None`` if
                unavailable (degraded / DB-offline mode).
            is_resumed: ``True`` when an existing session was resumed;
                ``False`` when a brand-new session was created.
        """
        session_label = session_id[:8] if session_id else "offline"
        action = "resumed" if is_resumed else "new"

        if self._rich:
            banner_text = (
                f"[bold cyan]TradeReady Agent v{_AGENT_VERSION}[/bold cyan]  "
                f"[dim]— Type[/dim] [green]/help[/green] [dim]for commands,[/dim] "
                f"[green]/quit[/green] [dim]to exit[/dim]\n"
                f"[dim]Session:[/dim] [yellow]{session_label}[/yellow] "
                f"[dim]({action})[/dim]"
            )
            self._console.print(_RichPanel(banner_text, border_style="cyan"))
        else:
            print(f"TradeReady Agent v{_AGENT_VERSION} — Type /help for commands, /quit to exit")  # noqa: T201
            print(f"Session: {session_label} ({action})")  # noqa: T201
            print()  # noqa: T201

    # ------------------------------------------------------------------
    # User / agent turns
    # ------------------------------------------------------------------

    def print_agent_reply(self, reply: str) -> None:
        """Render the agent's reply to the terminal.

        Attempts to render markdown when ``rich`` is available.

        Args:
            reply: The agent's response text (may contain Markdown).
        """
        if self._rich:
            self._console.print("[bold green]Agent:[/bold green]", end=" ")
            self._console.print(_RichMarkdown(reply))
        else:
            prefix = "Agent: "
            # Simple word-wrap for long lines
            words = reply.split()
            line: list[str] = []
            col = len(prefix)
            print(prefix, end="")  # noqa: T201
            for word in words:
                if col + len(word) + 1 > _PLAIN_WRAP_WIDTH and line:
                    print(" ".join(line))  # noqa: T201
                    print("       ", end="")  # noqa: T201
                    line = [word]
                    col = 7 + len(word)
                else:
                    line.append(word)
                    col += len(word) + 1
            if line:
                print(" ".join(line))  # noqa: T201
            print()  # noqa: T201

    def print_error(self, message: str) -> None:
        """Render an error message.

        Args:
            message: Human-readable error description.
        """
        if self._rich:
            self._console.print(f"[bold red]Error:[/bold red] {message}")
        else:
            print(f"Error: {message}", file=sys.stderr)  # noqa: T201

    def print_info(self, message: str) -> None:
        """Render an informational message (not an agent reply).

        Args:
            message: Info text to display.
        """
        if self._rich:
            self._console.print(f"[dim]{message}[/dim]")
        else:
            print(message)  # noqa: T201

    def print_command_output(self, title: str, content: str) -> None:
        """Render structured command output in a panel.

        Args:
            title: Panel / section title.
            content: Pre-formatted text to display inside the panel.
        """
        if self._rich:
            self._console.print(_RichPanel(content, title=title, border_style="blue"))
        else:
            print(f"--- {title} ---")  # noqa: T201
            print(content)  # noqa: T201
            print("-" * (len(title) + 8))  # noqa: T201

    def print_table(self, headers: list[str], rows: list[list[str]], title: str = "") -> None:
        """Render a data table.

        Args:
            headers: Column header strings.
            rows: List of row lists (each inner list must match ``headers``
                length).
            title: Optional table title.
        """
        if self._rich:
            table = _RichTable(title=title if title else None, border_style="dim")
            for h in headers:
                table.add_column(h, style="cyan")
            for row in rows:
                table.add_row(*row)
            self._console.print(table)
        else:
            if title:
                print(f"  {title}")  # noqa: T201
            col_widths = [
                max(len(headers[i]), max((len(r[i]) for r in rows), default=0))
                for i in range(len(headers))
            ]
            header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
            sep_line = "  ".join("-" * w for w in col_widths)
            print(header_line)  # noqa: T201
            print(sep_line)  # noqa: T201
            for row in rows:
                print("  ".join(row[i].ljust(col_widths[i]) for i in range(len(row))))  # noqa: T201
            print()  # noqa: T201

    def prompt(self) -> str:
        """Display the input prompt and read one line from stdin.

        Returns:
            The stripped user input.  Returns empty string on EOF.
        """
        if self._rich:
            # Rich does not buffer stdin; use built-in input() with a styled prefix.
            try:
                return input("\n[bold blue]You:[/bold blue] " if not _RICH_AVAILABLE else "")
            except (EOFError, KeyboardInterrupt):
                return ""
        try:
            # Plain fallback
            text = input("\nYou: ")
            return text.strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    def read_line(self) -> str:
        """Read one line from stdin, handling EOF / Ctrl-C gracefully.

        Returns:
            The stripped input string, or empty string on EOF.
        """
        try:
            if self._rich:
                raw = self._console.input("[bold blue]You:[/bold blue] ")
            else:
                raw = input("\nYou: ")
            return raw.strip()
        except (EOFError, KeyboardInterrupt):
            return ""


# ---------------------------------------------------------------------------
# Slash-command handlers
# ---------------------------------------------------------------------------


def _build_help_text() -> str:
    """Return the formatted help text listing all slash commands.

    Returns:
        Multi-line string listing each slash command and its description.
    """
    lines = [
        "/help                          Show this help message",
        "/trade [symbol] [direction]    Initiate trade discussion (e.g. /trade BTCUSDT buy)",
        "/analyze [symbol]              Analyse a specific market  (e.g. /analyze ETHUSDT)",
        "/portfolio                     Show portfolio summary",
        "/journal [entry]               Write a journal entry, or read recent entries",
        "/learn                         Show recent learnings / knowledge entries",
        "/permissions                   Show current agent permissions and risk limits",
        "/status                        Agent health and connection stats",
        "/session new                   Start a new conversation session",
        "/session list                  List recent sessions for this agent",
        "/session resume <ID>           Resume a session by ID prefix",
        "/quit  /exit                   Exit the REPL",
    ]
    return "\n".join(lines)


def _build_status_text(server: AgentServer, session_id: str | None, started_at: datetime) -> str:
    """Return a formatted status summary string.

    Args:
        server: The active :class:`~agent.server.AgentServer` instance.
        session_id: Current session UUID string, or ``None``.
        started_at: The time the REPL started.

    Returns:
        Multi-line status string.
    """
    uptime = (datetime.now(UTC) - started_at).total_seconds()
    lines = [
        f"Agent ID    : {server._agent_id}",
        f"Session ID  : {session_id or 'none (offline mode)'}",
        f"Uptime      : {uptime:.0f}s",
        f"Model       : {server._config.agent_model}",
        f"Platform    : {server._config.platform_base_url}",
        f"Errors      : {server._consecutive_errors}",
        f"Server ready: {'yes' if server._pydantic_agent is not None else 'no (degraded)'}",
    ]
    return "\n".join(lines)


def _build_permissions_text(config: AgentConfig) -> str:
    """Return a formatted permissions summary string.

    Args:
        config: The active :class:`~agent.config.AgentConfig`.

    Returns:
        Multi-line permissions string.
    """
    lines = [
        f"Role              : {config.default_agent_role}",
        f"Max trades/day    : {config.default_max_trades_per_day}",
        f"Max exposure      : {config.default_max_exposure_pct:.1f}%",
        f"Max daily loss    : {config.default_max_daily_loss_pct:.1f}%",
        f"Max trade size    : {config.max_trade_pct * 100:.1f}% of equity",
        f"Min confidence    : {config.trading_min_confidence:.2f}",
        f"Trading interval  : {config.trading_loop_interval}s",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Session management helpers
# ---------------------------------------------------------------------------


async def _list_sessions_text(agent_id: str, config: AgentConfig) -> str:
    """Fetch and format recent sessions for the given agent.

    Falls back gracefully when the DB is unavailable.

    Args:
        agent_id: The agent UUID string.
        config: Active :class:`~agent.config.AgentConfig`.

    Returns:
        Formatted multi-line string of recent sessions.
    """
    try:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: PLC0415
        from src.config import get_settings  # noqa: PLC0415
        from src.database.repositories.agent_session_repo import (  # noqa: PLC0415
            AgentSessionRepository,
        )

        settings = get_settings()
        engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        from uuid import UUID  # noqa: PLC0415

        agent_uuid = UUID(agent_id)
        async with factory() as db:
            repo = AgentSessionRepository(db)
            sessions = await repo.list_by_agent(agent_uuid, limit=10)

        if not sessions:
            return "No sessions found for this agent."

        lines = []
        for s in sessions:
            status = "active" if s.is_active else "closed"
            created = s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "unknown"
            short_id = str(s.id)[:8]
            title = (s.title or "(untitled)")[:30]
            lines.append(f"  {short_id}  {status:6}  {created}  {title}")
        return "\n".join(lines)

    except Exception as exc:  # noqa: BLE001
        logger.warning("agent.server.cli.list_sessions.failed", error=str(exc))
        return f"(Could not load session list — DB unavailable: {exc})"


# ---------------------------------------------------------------------------
# Core REPL loop
# ---------------------------------------------------------------------------


async def run_chat(
    *,
    agent_id: str | None = None,
    session_id: str | None = None,
    config: AgentConfig | None = None,
) -> None:
    """Run the interactive CLI REPL until the user quits.

    This is the main entry point for the ``chat`` subcommand.  It:

    1. Loads :class:`~agent.config.AgentConfig` from ``agent/.env`` (unless
       *config* is supplied directly).
    2. Constructs and starts an :class:`~agent.server.AgentServer` for the
       given agent.
    3. Prints the welcome banner.
    4. Enters the read-eval-print loop, routing each message through:

       a. Local slash-command handlers (``/help``, ``/quit``, etc.).
       b. :class:`~agent.conversation.IntentRouter` for intent classification.
       c. :meth:`~agent.server.AgentServer.process_message` for LLM reasoning.

    5. Handles Ctrl-C gracefully (prints a newline and exits).
    6. Calls :meth:`~agent.server.AgentServer.stop` before returning so
       the session is properly closed.

    Args:
        agent_id: UUID string of the agent to chat with.  Falls back to
            :data:`_DEFAULT_AGENT_ID` when ``None``.
        session_id: UUID string of a specific session to resume.  When
            ``None``, the most recent active session is resumed or a new one
            is created.
        config: Pre-built :class:`~agent.config.AgentConfig` instance.
            When ``None``, one is loaded from ``agent/.env``.

    Raises:
        SystemExit: On config load failure (exits with code 1).
    """
    # ── Load config ──────────────────────────────────────────────────────────
    if config is None:
        try:
            config = AgentConfig()
        except Exception as exc:  # noqa: BLE001
            print(  # noqa: T201
                f"ERROR: Failed to load agent configuration.\n"
                f"  Make sure agent/.env exists and contains OPENROUTER_API_KEY.\n"
                f"  Details: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

    # ── Resolve agent ID ─────────────────────────────────────────────────────
    effective_agent_id = agent_id or _DEFAULT_AGENT_ID

    # ── Build UI and server ──────────────────────────────────────────────────
    ui = TerminalUI()
    router = IntentRouter()
    server = AgentServer(agent_id=effective_agent_id, config=config)

    # Track when the REPL started for uptime reporting.
    repl_started_at = datetime.now(UTC)

    # ── Initialise the server (DB, Redis, Pydantic AI agent) ─────────────────
    ui.print_info("Connecting to platform…")
    try:
        await server._init_dependencies()
        await server._init_pydantic_agent()
    except Exception as exc:  # noqa: BLE001
        ui.print_error(f"Server initialisation failed: {exc}")
        logger.warning("agent.server.cli.server_init_failed", error=str(exc))
        # Continue in degraded mode — session will be None.

    # ── Create or resume the conversation session ────────────────────────────
    # If a specific session_id was requested, inject it into the AgentSession.
    try:
        from agent.conversation.session import AgentSession  # noqa: PLC0415

        _session_factory = getattr(server, "_session_factory", None)
        if _session_factory is not None:
            ag_session = AgentSession(
                agent_id=effective_agent_id,
                session_factory=_session_factory,
                session_id=session_id,
                config=config,
            )
            await ag_session.start()
            server._session = ag_session
            is_resumed = session_id is not None or bool(ag_session.session_id)
        else:
            ag_session = None
            is_resumed = False
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent.server.cli.session_start_failed", error=str(exc))
        ag_session = None
        is_resumed = False

    # ── Banner ───────────────────────────────────────────────────────────────
    displayed_session_id = str(ag_session.session_id) if ag_session and ag_session.session_id else None
    ui.print_banner(displayed_session_id, is_resumed)

    # ── REPL ─────────────────────────────────────────────────────────────────
    try:
        while True:
            raw = ui.read_line()

            if not raw:
                # Empty input or EOF — skip.
                if raw == "":
                    # Distingush EOF (read_line returns "" on Ctrl-D too)
                    # but just continue; Ctrl-C is handled by KeyboardInterrupt.
                    continue

            stripped = raw.strip()
            if not stripped:
                continue

            # ── Slash command dispatch ────────────────────────────────────
            if stripped.startswith("/"):
                should_exit = await _handle_slash_command(
                    stripped, ui, router, server, ag_session,
                    effective_agent_id, config, repl_started_at,
                    displayed_session_id,
                )
                if should_exit:
                    break
                continue

            # ── Natural language — intent route then LLM ──────────────────
            intent = router.classify(stripped)
            logger.debug("agent.server.cli.intent_classified", intent=intent.value, message_preview=stripped[:60])

            # For all intents we forward the message to the server reasoning
            # loop which handles the LLM call and session persistence.
            if ag_session is not None and ag_session.is_active:
                reply = await server.process_message(stripped, ag_session)
            else:
                # No active session (DB offline) — use reasoning loop directly
                # without session persistence.
                try:
                    reply = await server._reasoning_loop([], stripped)
                except Exception as exc:  # noqa: BLE001
                    reply = f"(Error: {exc})"

            ui.print_agent_reply(reply)

    except KeyboardInterrupt:
        print()  # noqa: T201  # newline after ^C
        ui.print_info("Interrupted. Closing session…")

    # ── Shutdown ─────────────────────────────────────────────────────────────
    finally:
        if ag_session is not None and ag_session.is_active:
            try:

                await ag_session.end()
            except Exception as exc:  # noqa: BLE001
                logger.warning("agent.server.cli.session_end_failed", error=str(exc))
        ui.print_info("Session closed. Goodbye.")


# ---------------------------------------------------------------------------
# Slash-command router
# ---------------------------------------------------------------------------


async def _handle_slash_command(
    raw: str,
    ui: TerminalUI,
    router: IntentRouter,
    server: AgentServer,
    ag_session: object | None,
    agent_id: str,
    config: AgentConfig,
    repl_started_at: datetime,
    current_session_id: str | None,
) -> bool:
    """Dispatch a slash command to its handler and return whether to exit.

    Args:
        raw: The raw slash command string (e.g. ``"/portfolio"``).
        ui: Active :class:`TerminalUI` instance for rendering output.
        router: Active :class:`~agent.conversation.IntentRouter`.
        server: Active :class:`~agent.server.AgentServer`.
        ag_session: The current :class:`~agent.conversation.AgentSession`,
            or ``None`` in offline mode.
        agent_id: The agent UUID string.
        config: Active :class:`~agent.config.AgentConfig`.
        repl_started_at: UTC datetime when the REPL was started.
        current_session_id: Current session UUID string or ``None``.

    Returns:
        ``True`` when the REPL should exit; ``False`` otherwise.
    """
    parts = raw.split()
    cmd = parts[0].lstrip("/").lower()
    args = parts[1:]

    # /quit and /exit
    if cmd in ("quit", "exit"):
        ui.print_info("Exiting…")
        return True

    # /help
    if cmd == "help":
        ui.print_command_output("Available Commands", _build_help_text())
        return False

    # /status
    if cmd in ("status", "health", "ping", "info"):
        text = _build_status_text(server, current_session_id, repl_started_at)
        ui.print_command_output("Agent Status", text)
        return False

    # /permissions
    if cmd in ("permissions", "permission", "access", "role"):
        text = _build_permissions_text(config)
        ui.print_command_output("Current Permissions", text)
        return False

    # /portfolio
    if cmd in ("portfolio", "balance", "positions", "pnl"):
        message = f"/portfolio {' '.join(args)}".strip() if args else "show my portfolio summary"
        await _dispatch_to_server(message, ui, server, ag_session, router)
        return False

    # /trade [symbol] [direction]
    if cmd in ("trade", "buy", "sell", "order"):
        if args:
            symbol = args[0].upper()
            direction = args[1].lower() if len(args) > 1 else ""
            message = f"I want to {direction + ' ' if direction else ''}trade {symbol}"
        else:
            message = "Let's discuss a trade opportunity"
        await _dispatch_to_server(message, ui, server, ag_session, router)
        return False

    # /analyze [symbol]
    if cmd in ("analyze", "analyse", "analysis", "chart"):
        if args:
            symbol = args[0].upper()
            message = f"Analyse {symbol} for me"
        else:
            message = "Analyse the current market conditions"
        await _dispatch_to_server(message, ui, server, ag_session, router)
        return False

    # /journal [entry text]
    if cmd in ("journal", "log", "note"):
        if args:
            entry_text = " ".join(args)
            message = f"Journal entry: {entry_text}"
        else:
            message = "Show me my recent journal entries"
        await _dispatch_to_server(message, ui, server, ag_session, router)
        return False

    # /learn
    if cmd in ("learn", "explain"):
        if args:
            message = f"Explain {' '.join(args)}"
        else:
            message = "What are my recent learnings and market insights?"
        await _dispatch_to_server(message, ui, server, ag_session, router)
        return False

    # /session [new|list|resume <id>]
    if cmd == "session":
        await _handle_session_command(args, ui, agent_id, config, server, ag_session)
        return False

    # Unknown slash command — let the intent router try to classify the
    # remainder as natural language.
    remainder = " ".join(parts[1:]) if len(parts) > 1 else raw
    ui.print_info(f"Unknown command '/{cmd}'. Treating as message…")
    await _dispatch_to_server(remainder or raw, ui, server, ag_session, router)
    return False


async def _dispatch_to_server(
    message: str,
    ui: TerminalUI,
    server: AgentServer,
    ag_session: object | None,
    router: IntentRouter,
) -> None:
    """Send *message* through the server reasoning loop and display the reply.

    Falls back to a no-session reasoning call when ``ag_session`` is
    ``None`` or not active.

    Args:
        message: The message to process.
        ui: Active :class:`TerminalUI` for output.
        server: Active :class:`~agent.server.AgentServer`.
        ag_session: Current :class:`~agent.conversation.AgentSession` or
            ``None``.
        router: Active :class:`~agent.conversation.IntentRouter` (unused
            directly but kept for future hook points).
    """
    try:
        from agent.conversation.session import AgentSession  # noqa: PLC0415

        if ag_session is not None and isinstance(ag_session, AgentSession) and ag_session.is_active:
            reply = await server.process_message(message, ag_session)
        else:
            reply = await server._reasoning_loop([], message)
    except Exception as exc:  # noqa: BLE001
        reply = f"(Error processing request: {exc})"
        logger.warning("agent.server.cli.dispatch_failed", error=str(exc))

    ui.print_agent_reply(reply)


async def _handle_session_command(
    args: list[str],
    ui: TerminalUI,
    agent_id: str,
    config: AgentConfig,
    server: AgentServer,
    ag_session: object | None,
) -> None:
    """Handle the ``/session`` sub-command family.

    Subcommands:
    * ``new`` — end the current session and start a new one.
    * ``list`` — list recent sessions for the agent.
    * ``resume <id>`` — resume a session by ID prefix.
    * (no arg) — show current session ID.

    Args:
        args: Remaining command tokens after ``/session``.
        ui: Active :class:`TerminalUI` for output.
        agent_id: The agent UUID string.
        config: Active :class:`~agent.config.AgentConfig`.
        server: Active :class:`~agent.server.AgentServer`.
        ag_session: Current session or ``None``.
    """
    from agent.conversation.session import AgentSession, SessionError  # noqa: PLC0415

    if not args:
        # Show current session
        if ag_session is not None and isinstance(ag_session, AgentSession):
            sid = str(ag_session.session_id) if ag_session.session_id else "none"
            ui.print_command_output("Current Session", f"Session ID: {sid}\nActive: {ag_session.is_active}")
        else:
            ui.print_info("No active session (offline mode).")
        return

    sub = args[0].lower()

    if sub == "list":
        ui.print_info("Loading sessions…")
        text = await _list_sessions_text(agent_id, config)
        ui.print_command_output("Recent Sessions", text)
        return

    if sub == "new":
        # Close current session and create a new one.
        if ag_session is not None and isinstance(ag_session, AgentSession) and ag_session.is_active:
            try:
                await ag_session.end()
                ui.print_info("Previous session closed.")
            except SessionError as exc:
                ui.print_error(f"Could not close current session: {exc}")

        _session_factory = getattr(server, "_session_factory", None)
        if _session_factory is None:
            ui.print_error("Cannot create new session — DB unavailable.")
            return

        try:
            new_session = AgentSession(
                agent_id=agent_id,
                session_factory=_session_factory,
                config=config,
            )
            await new_session.start()
            server._session = new_session
            new_id = str(new_session.session_id)[:8] if new_session.session_id else "unknown"
            ui.print_info(f"New session started: {new_id}")
        except SessionError as exc:
            ui.print_error(f"Failed to start new session: {exc}")
        return

    if sub == "resume":
        if len(args) < 2:
            ui.print_error("Usage: /session resume <session-id>")
            return
        target_id = args[1]

        _session_factory = getattr(server, "_session_factory", None)
        if _session_factory is None:
            ui.print_error("Cannot resume session — DB unavailable.")
            return

        try:
            resumed = AgentSession(
                agent_id=agent_id,
                session_factory=_session_factory,
                session_id=target_id,
                config=config,
            )
            await resumed.start()
            server._session = resumed
            display_id = str(resumed.session_id)[:8] if resumed.session_id else target_id
            ui.print_info(f"Session resumed: {display_id}")
        except Exception as exc:  # noqa: BLE001
            ui.print_error(f"Could not resume session '{target_id}': {exc}")
        return

    ui.print_error(f"Unknown /session subcommand '{sub}'. Use: new | list | resume <id>")
