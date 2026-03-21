"""Agent configuration loaded from environment variables via pydantic-settings."""

from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the .env file path relative to this file (agent/.env)
_ENV_FILE = Path(__file__).parent / ".env"


class AgentConfig(BaseSettings):
    """All runtime configuration for the TradeReady Platform Testing Agent.

    Values are read from environment variables or from a `.env` file located
    in the ``agent/`` directory.  Every field maps 1-to-1 with an entry in
    ``agent/.env.example``.

    Example::

        config = AgentConfig()
        print(config.platform_base_url)
        print(config.platform_root)
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── OpenRouter / LLM ──────────────────────────────────────────────────────
    openrouter_api_key: str
    agent_model: str = "openrouter:anthropic/claude-sonnet-4-5"
    agent_cheap_model: str = "openrouter:google/gemini-2.0-flash-001"

    # ── Platform connectivity ─────────────────────────────────────────────────
    platform_base_url: str = "http://localhost:8000"
    platform_api_key: str = ""
    platform_api_secret: str = ""

    # ── Agent behaviour ───────────────────────────────────────────────────────
    max_trade_pct: float = 0.05
    symbols: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    # ── Memory settings ───────────────────────────────────────────────────────
    memory_search_limit: int = 10
    memory_cache_ttl: int = 3600  # seconds
    memory_cleanup_confidence_threshold: float = 0.2
    memory_cleanup_age_days: int = 90

    # ── Conversation settings ─────────────────────────────────────────────────
    context_max_tokens: int = 8000
    context_recent_messages: int = 20
    context_summary_threshold: int = 50  # summarize after N messages

    # ── Server settings ───────────────────────────────────────────────────────
    agent_server_host: str = "0.0.0.0"
    agent_server_port: int = 8001
    agent_health_check_interval: int = 60  # seconds
    agent_scheduled_review_hour: int = 8  # UTC hour for morning review

    # ── Permission defaults ───────────────────────────────────────────────────
    # Default to the least-privileged role so agents without explicit permission
    # records cannot trade.  Override to "paper_trader" or higher only after
    # explicit review of the agent's risk profile.
    default_agent_role: str = "viewer"
    default_max_trades_per_day: int = 50
    default_max_exposure_pct: float = 25.0
    default_max_daily_loss_pct: float = 5.0

    # ── Trading loop settings ─────────────────────────────────────────────────
    trading_loop_interval: int = 3600  # seconds (1 hour)
    trading_min_confidence: float = 0.6

    # ── Computed ──────────────────────────────────────────────────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def platform_root(self) -> Path:
        """Absolute path to the project root (parent of the ``agent/`` directory).

        Used when spawning the MCP server subprocess, which must be started
        from the project root so that ``python -m src.mcp.server`` resolves
        correctly.

        Returns:
            The resolved project root directory as a :class:`pathlib.Path`.
        """
        return Path(__file__).parent.parent.resolve()
