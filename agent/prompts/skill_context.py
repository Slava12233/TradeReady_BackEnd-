"""Skill context loader for the TradeReady Platform Testing Agent.

Loads the platform's skill document (docs/skill.md) into a string so it can be
appended to the agent's system prompt or passed as additional context.  The
loader tries two sources in order:

1. Local filesystem — ``config.platform_root / "docs" / "skill.md"``
2. Remote REST API — ``{config.platform_base_url}/api/v1/docs/skill``

If both sources fail the function returns an empty string and logs a warning.
It never raises.
"""

from __future__ import annotations

import structlog

from agent.config import AgentConfig

logger = structlog.get_logger(__name__)


async def load_skill_context(config: AgentConfig) -> str:
    """Load the platform skill document for use as additional agent context.

    Attempts to read ``docs/skill.md`` from the local filesystem first.  If the
    file is missing or unreadable, falls back to fetching the document from the
    platform's REST API at ``GET /api/v1/docs/skill``.  Returns an empty string
    if both sources fail — the agent can still operate without skill context.

    Args:
        config: Resolved :class:`~agent.config.AgentConfig` instance.  Uses
            ``config.platform_root`` for the local file path and
            ``config.platform_base_url`` for the fallback HTTP fetch.

    Returns:
        The raw Markdown text of ``docs/skill.md``, or an empty string if the
        document could not be loaded from either source.

    Example::

        config = AgentConfig()
        skill_text = await load_skill_context(config)
        full_prompt = SYSTEM_PROMPT + ("\\n\\n" + skill_text if skill_text else "")
    """
    # ── 1. Try local filesystem ───────────────────────────────────────────────
    skill_path = config.platform_root / "docs" / "skill.md"
    try:
        content = skill_path.read_text(encoding="utf-8")
        logger.debug("agent.api.skill_context.loaded_from_disk", path=str(skill_path))
        return content
    except FileNotFoundError:
        logger.debug(
            "agent.api.skill_context.file_not_found",
            path=str(skill_path),
            fallback="remote_api",
        )
    except OSError as exc:
        logger.warning(
            "agent.api.skill_context.disk_read_error",
            path=str(skill_path),
            error=str(exc),
            fallback="remote_api",
        )

    # ── 2. Fallback: fetch from the platform REST API ─────────────────────────
    try:
        import httpx  # noqa: PLC0415 — lazy import; httpx may not always be present

        url = f"{config.platform_base_url.rstrip('/')}/api/v1/docs/skill"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            # The route returns plain Markdown text (Content-Type: text/plain).
            # If the server wraps it in JSON, fall back to .text.
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                payload = response.json()
                # Expect {"content": "..."} shape from the Next.js Route Handler.
                text: str = payload.get("content", "") or ""
            else:
                text = response.text
            logger.debug(
                "agent.api.skill_context.loaded_from_api",
                url=url,
                bytes=len(text),
            )
            return text
    except ImportError:
        logger.warning("agent.api.skill_context.httpx_not_installed", source="remote_api")
    except Exception as exc:  # noqa: BLE001 — intentional catch-all; never crash
        logger.warning(
            "agent.api.skill_context.api_fetch_failed",
            url=f"{config.platform_base_url}/api/v1/docs/skill",
            error=str(exc),
        )

    logger.warning("agent.api.skill_context.unavailable", reason="both_sources_failed")
    return ""
