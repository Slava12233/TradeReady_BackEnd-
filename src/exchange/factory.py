"""Factory for creating exchange adapters from application settings.

Provides a convenient way to create :class:`CCXTAdapter` instances
configured from ``src.config.Settings`` without requiring callers
to know about CCXT configuration details.

Example::

    adapter = create_adapter()           # uses settings.exchange_id
    adapter = create_adapter("okx")      # explicit exchange
    await adapter.initialize()
"""

from __future__ import annotations

from typing import Any

import structlog

from src.exchange.ccxt_adapter import CCXTAdapter

log = structlog.get_logger(__name__)


def create_adapter(
    exchange_id: str | None = None,
    api_key: str | None = None,
    secret: str | None = None,
) -> CCXTAdapter:
    """Create a :class:`CCXTAdapter` from settings or explicit parameters.

    Args:
        exchange_id: Override exchange (default: ``settings.exchange_id``).
        api_key: Override API key (default: ``settings.exchange_api_key``).
        secret: Override secret (default: ``settings.exchange_secret``).

    Returns:
        An uninitialized :class:`CCXTAdapter`.  Caller must call
        ``await adapter.initialize()`` before use.
    """
    from src.config import get_settings  # noqa: PLC0415

    settings = get_settings()

    eid = exchange_id or settings.exchange_id
    key = api_key or settings.exchange_api_key
    sec = secret or settings.exchange_secret

    config: dict[str, Any] = {}
    if key:
        config["apiKey"] = key
    if sec:
        config["secret"] = sec

    log.info("Creating exchange adapter", exchange=eid, authenticated=bool(key))
    return CCXTAdapter(eid, config)


def get_additional_exchange_ids() -> list[str]:
    """Parse the comma-separated ``additional_exchanges`` setting.

    Returns:
        List of lowercase exchange IDs (empty list if none configured).
    """
    from src.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    raw = settings.additional_exchanges.strip()
    if not raw:
        return []
    return [eid.strip().lower() for eid in raw.split(",") if eid.strip()]
