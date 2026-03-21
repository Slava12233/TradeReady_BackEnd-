"""Middleware for logging all outbound API calls from the agent.

This module provides:

- :func:`log_api_call` — an async context manager that wraps every outbound
  API call, records latency, emits structured log lines on completion and
  failure, and propagates exceptions unchanged.
- :func:`estimate_llm_cost` — a helper that converts token counts into an
  approximate USD cost using a table of known model prices.

Usage::

    from agent.logging_middleware import log_api_call, estimate_llm_cost

    async with log_api_call("sdk", "get_price", symbol="BTCUSDT") as ctx:
        result = await client.get_price("BTCUSDT")
        ctx["response_status"] = 200

    cost = estimate_llm_cost("anthropic/claude-sonnet", 1200, 400)
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Approximate per-token costs in USD (updated periodically)
# ---------------------------------------------------------------------------

_MODEL_COSTS: dict[str, dict[str, float]] = {
    "anthropic/claude-sonnet": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "anthropic/claude-haiku": {"input": 0.25 / 1_000_000, "output": 1.25 / 1_000_000},
    "google/gemini-2.0-flash": {"input": 0.1 / 1_000_000, "output": 0.4 / 1_000_000},
}


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def log_api_call(
    channel: str,
    endpoint: str,
    method: str = "",
    **extra_context: Any,  # noqa: ANN401
) -> AsyncGenerator[dict[str, Any], None]:
    """Context manager that logs API call start, duration, and outcome.

    Emits ``agent.api.completed`` on success and ``agent.api.failed`` on any
    exception.  The yielded *ctx* dictionary may be mutated inside the
    ``async with`` block to attach response metadata (e.g. HTTP status) that
    will appear in the log line.

    Exceptions are always re-raised after the ``agent.api.failed`` log line
    is emitted so that callers can handle them normally.

    Args:
        channel: Integration channel identifier.  One of ``"sdk"``,
            ``"mcp"``, ``"rest"``, or ``"db"``.
        endpoint: Destination identifier — either a URL path such as
            ``"/api/v1/trade/order"`` or a tool/method name such as
            ``"get_price"``.
        method: HTTP verb (``"GET"``, ``"POST"``, …).  Pass an empty string
            (the default) for non-HTTP channels such as ``"sdk"`` or
            ``"mcp"``.
        **extra_context: Arbitrary keyword arguments that are merged into the
            yielded context dict and included in the success log line when
            their values are not ``None``.

    Yields:
        A mutable ``dict[str, Any]`` pre-populated with the supplied
        *extra_context* plus ``response_status=None`` and ``error=None``.
        Callers should set ``ctx["response_status"]`` to the HTTP status
        code (or equivalent) after the call succeeds.

    Example::

        async with log_api_call("rest", "/api/v1/trade/order", "POST",
                                symbol="BTCUSDT") as ctx:
            resp = await http_client.post("/api/v1/trade/order", json=body)
            ctx["response_status"] = resp.status_code
    """
    from agent.logging import new_span_id  # noqa: PLC0415

    span_id = new_span_id()
    ctx: dict[str, Any] = {"response_status": None, "error": None, **extra_context}
    start = time.monotonic()

    try:
        yield ctx
    except Exception as exc:
        ctx["error"] = f"{type(exc).__name__}: {exc}"
        ctx["response_status"] = getattr(exc, "status_code", 0)
        latency_err = round((time.monotonic() - start) * 1000, 2)
        logger.error(
            "agent.api.failed",
            channel=channel,
            endpoint=endpoint,
            method=method,
            span_id=span_id,
            latency_ms=latency_err,
            **{k: v for k, v in ctx.items() if v is not None},
        )
        # Emit error metric
        try:
            from agent.logging import get_agent_id  # noqa: PLC0415
            from agent.metrics import agent_api_errors_total  # noqa: PLC0415

            agent_api_errors_total.labels(
                agent_id=get_agent_id(),
                channel=channel,
                endpoint=endpoint,
                error_type=type(exc).__name__,
            ).inc()
        except Exception:  # noqa: BLE001
            pass
        raise
    else:
        latency = round((time.monotonic() - start) * 1000, 2)
        logger.info(
            "agent.api.completed",
            channel=channel,
            endpoint=endpoint,
            method=method,
            span_id=span_id,
            latency_ms=latency,
            status=ctx.get("response_status"),
        )
        # Emit duration metric (convert ms → seconds)
        try:
            from agent.logging import get_agent_id  # noqa: PLC0415
            from agent.metrics import agent_api_call_duration  # noqa: PLC0415

            agent_api_call_duration.labels(
                agent_id=get_agent_id(),
                channel=channel,
                endpoint=endpoint,
            ).observe(latency / 1000)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# LLM cost estimator
# ---------------------------------------------------------------------------


def estimate_llm_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for an LLM call based on approximate per-token pricing.

    Performs a two-phase lookup against :data:`_MODEL_COSTS`:

    1. Exact match on the *model* string.
    2. Substring match — checks whether any known key is a substring of
       *model* or vice-versa (handles OpenRouter prefixes such as
       ``"openrouter:anthropic/claude-sonnet"``).

    Returns ``0.0`` when no pricing entry is found rather than raising an
    exception, so callers can safely call this function for unknown models
    and treat the result as an informational metric.

    Args:
        model: Model identifier string.  May include provider prefixes such
            as ``"openrouter:anthropic/claude-sonnet-4-5"``; the lookup is
            flexible enough to match partial strings.
        input_tokens: Number of tokens in the prompt sent to the model.
        output_tokens: Number of tokens in the completion returned by the
            model.

    Returns:
        Estimated cost in US dollars as a ``float``.  Returns ``0.0`` when
        the model is not in the pricing table.

    Example::

        cost = estimate_llm_cost("anthropic/claude-sonnet", 1200, 400)
        # cost ≈ 0.0000096
    """
    costs = _MODEL_COSTS.get(model)
    if not costs:
        for key, val in _MODEL_COSTS.items():
            if key in model or model in key:
                costs = val
                break
    if not costs:
        return 0.0
    return input_tokens * costs["input"] + output_tokens * costs["output"]
