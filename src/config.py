"""Application configuration loaded from environment variables via pydantic-settings."""

from decimal import Decimal
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration for the AI Agent Crypto Trading Platform.

    Values are read from environment variables or from a `.env` file in the
    working directory.  Every field maps 1-to-1 with an entry in `.env.example`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://agentexchange:change_me_in_production@timescaledb:5432/agentexchange",
        description="Async SQLAlchemy connection string (asyncpg driver).",
    )
    postgres_user: str = Field(default="agentexchange")
    postgres_password: str = Field(default="change_me_in_production")
    postgres_db: str = Field(default="agentexchange")

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://redis:6379/0",
        description="Redis connection URL used for cache, pub/sub, and rate limiting.",
    )

    # ── Binance WebSocket ─────────────────────────────────────────────────────
    binance_ws_url: str = Field(
        default="wss://stream.binance.com:9443/stream",
        description="Base URL for the Binance combined stream endpoint.",
    )

    # ── Exchange Connectivity (CCXT) ──────────────────────────────────────────
    exchange_id: str = Field(
        default="binance",
        description="Primary exchange identifier for CCXT (e.g. binance, okx, bybit).",
    )
    exchange_api_key: str | None = Field(
        default=None,
        description="API key for authenticated exchange operations (Phase 8 live trading).",
    )
    exchange_secret: str | None = Field(
        default=None,
        description="API secret for authenticated exchange operations (Phase 8 live trading).",
    )
    additional_exchanges: str = Field(
        default="",
        description="Comma-separated list of additional exchange IDs for multi-exchange ingestion.",
    )

    # ── API Server ────────────────────────────────────────────────────────────
    api_host: str = Field(default="0.0.0.0")  # noqa: S104
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_base_url: str = Field(default="https://api.agentexchange.com")

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001,https://tradeready.io,https://www.tradeready.io",
        description="Comma-separated list of allowed CORS origins. Wildcard '*' is forbidden.",
    )

    # ── Authentication ────────────────────────────────────────────────────────
    jwt_secret: str = Field(
        description="Secret key for JWT signing.  Must be at least 32 characters.",
    )
    jwt_expiry_hours: int = Field(default=1, ge=1, le=168)

    # ── Trading Defaults ──────────────────────────────────────────────────────
    default_starting_balance: Decimal = Field(
        default=Decimal("10000"),
        description="Virtual USDT balance credited to every new account.",
    )
    trading_fee_pct: Decimal = Field(
        default=Decimal("0.1"),
        description="Simulated taker fee percentage (0.1 = 0.1 %).",
    )
    default_slippage_factor: Decimal = Field(
        default=Decimal("0.1"),
        description="Base slippage coefficient used by the slippage model.",
    )

    # ── Tick Ingestion ────────────────────────────────────────────────────────
    tick_flush_interval: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Seconds between periodic TickBuffer flushes to TimescaleDB.",
    )
    tick_buffer_max_size: int = Field(
        default=5000,
        ge=100,
        description="Maximum ticks held in memory before an immediate flush is triggered.",
    )

    # ── Webhooks ──────────────────────────────────────────────────────────────
    per_account_webhook_limit: int = Field(
        default=25,
        ge=1,
        description="Maximum number of webhook subscriptions allowed per account.",
    )

    # ── Monitoring ────────────────────────────────────────────────────────────
    grafana_admin_password: str = Field(default="change_me")

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_min_length(cls, value: str) -> str:
        """Ensure the JWT secret is long enough to be secure."""
        if len(value) < 32:
            raise ValueError("jwt_secret must be at least 32 characters long")
        return value

    @field_validator("cors_origins")
    @classmethod
    def _cors_no_wildcard(cls, value: str) -> str:
        """Reject wildcard '*' in CORS origins — incompatible with allow_credentials=True."""
        origins = [o.strip() for o in value.split(",") if o.strip()]
        if "*" in origins:
            raise ValueError("CORS_ORIGINS cannot contain '*' when allow_credentials=True")
        return value

    @field_validator("database_url")
    @classmethod
    def _database_url_asyncpg(cls, value: str) -> str:
        """Ensure the database URL uses the asyncpg driver."""
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must use the asyncpg driver (postgresql+asyncpg://...)")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call).

    Using ``lru_cache`` means the .env file is read exactly once per process,
    which is the expected behaviour for a FastAPI application.

    Example::

        settings = get_settings()
        print(settings.redis_url)
    """
    return Settings()  # type: ignore[call-arg]
