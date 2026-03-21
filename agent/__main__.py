"""Package entry point — allows running the agent as ``python -m agent``.

Dispatches to either the interactive REPL (``chat`` subcommand) or the
existing workflow runner (``smoke``, ``trade``, ``backtest``, ``strategy``,
``all``) depending on the first positional argument.

Usage::

    python -m agent chat                        # Interactive REPL
    python -m agent chat --agent-id <UUID>      # REPL for a specific agent
    python -m agent chat --session-id <UUID>    # REPL resuming a session
    python -m agent smoke                        # Connectivity smoke test
    python -m agent trade                        # Full trading workflow
    python -m agent backtest                     # Backtest workflow
    python -m agent strategy                     # Strategy workflow
    python -m agent all                          # Run all four workflows
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def _build_top_level_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser.

    The parser recognises ``chat`` as a special subcommand handled by
    :func:`agent.cli.run_chat`.  All other subcommands are forwarded to
    :func:`agent.main.main`.

    Returns:
        Configured :class:`~argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        prog="python -m agent",
        description=(
            "TradeReady Agent — interactive CLI and automated platform testing."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Subcommands:\n"
            "  chat       Interactive REPL — chat with the agent in your terminal\n"
            "  smoke      10-step connectivity validation (no LLM required)\n"
            "  trade      Full trading lifecycle: analyse → signal → execute → close\n"
            "  backtest   7-day MA-crossover backtest with LLM analysis\n"
            "  strategy   Create → test → improve → compare strategy versions\n"
            "  all        Run all four automated workflows in sequence\n"
        ),
        # Do NOT add_help here — the sub-parsers add their own help so that
        # "python -m agent chat --help" and "python -m agent smoke --help"
        # both produce context-aware output.
        add_help=True,
    )

    subparsers = parser.add_subparsers(dest="command", metavar="SUBCOMMAND")

    # ── chat subcommand ──────────────────────────────────────────────────────
    chat_parser = subparsers.add_parser(
        "chat",
        help="Interactive REPL — chat with the agent in your terminal",
        description=(
            "Start an interactive conversation with the TradeReady agent.\n"
            "Type /help inside the REPL to see all available slash commands."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    chat_parser.add_argument(
        "--agent-id",
        metavar="UUID",
        default=None,
        help=(
            "UUID of the agent to chat with.  "
            "Defaults to the first placeholder agent (00000000-0000-0000-0000-000000000001)."
        ),
    )
    chat_parser.add_argument(
        "--session-id",
        metavar="UUID",
        default=None,
        help=(
            "UUID of an existing session to resume.  "
            "When omitted the most recent active session is resumed or a new one is created."
        ),
    )

    # ── workflow subcommands (handled by agent.main.main) ────────────────────
    for name, help_text in (
        ("smoke", "10-step connectivity validation (no LLM required)"),
        ("trade", "Full trading lifecycle: analyse → signal → execute → close"),
        ("backtest", "7-day MA-crossover backtest with LLM analysis"),
        ("strategy", "Create → test → improve → compare strategy versions"),
        ("all", "Run all four automated workflows in sequence"),
    ):
        wf_parser = subparsers.add_parser(name, help=help_text)
        wf_parser.add_argument(
            "--model",
            metavar="MODEL_ID",
            default=None,
            help="Override LLM model (e.g. 'openrouter:anthropic/claude-opus-4-5')",
        )
        wf_parser.add_argument(
            "--output-dir",
            metavar="DIR",
            default=None,
            help="Directory to write JSON report files",
        )

    return parser


async def _run_chat(args: argparse.Namespace) -> None:
    """Launch the interactive REPL from parsed CLI arguments.

    Args:
        args: Parsed namespace from the ``chat`` subparser.  Expected
            attributes: ``agent_id`` (str | None), ``session_id`` (str | None).
    """
    from agent.cli import run_chat  # noqa: PLC0415

    await run_chat(
        agent_id=args.agent_id,
        session_id=args.session_id,
    )


def _run_workflow() -> None:
    """Delegate to :func:`agent.main.main` for all non-chat subcommands.

    Re-uses the original ``agent.main`` CLI parser so that ``--model`` and
    ``--output-dir`` flags continue to work exactly as documented.
    """
    from agent.main import main  # noqa: PLC0415

    asyncio.run(main())


def _entrypoint() -> None:
    """Parse the first argument and dispatch to the correct runner.

    When no argument (or an unrecognised argument) is given, the full
    ``agent.main`` parser is used so that existing error messages remain
    unchanged.
    """
    parser = _build_top_level_parser()

    # Peek at the first positional to decide dispatch — do not consume args
    # that belong to the workflow sub-parsers.
    first_arg = sys.argv[1] if len(sys.argv) > 1 else None

    if first_arg == "chat":
        # Parse only the chat-specific args; positional "chat" is consumed
        # by the subparser.
        args = parser.parse_args()
        asyncio.run(_run_chat(args))
    else:
        # Delegate everything to the original main() which has its own parser.
        # This preserves all existing behaviour for smoke/trade/backtest/strategy/all.
        _run_workflow()


_entrypoint()
