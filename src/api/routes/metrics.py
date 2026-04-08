"""Metrics routes for the AI Agent Crypto Trading Platform.

Implements advanced statistical metrics endpoints:

- ``POST /api/v1/metrics/deflated-sharpe`` — Deflated Sharpe Ratio (DSR)

The DSR (Bailey & Lopez de Prado, 2014) corrects the observed Sharpe Ratio
for multiple-testing bias.  When a researcher tests N strategy variants and
keeps the best, the winner is likely over-fitted.  DSR asks: is this Sharpe
still significant given that N strategies were tried?

This endpoint is **public** (no authentication required) so that it can be
called from the agent's strategy-testing workflow without needing an API key,
and from external tools that only have return series data.

Data flow::

    POST /api/v1/metrics/deflated-sharpe
      body: { returns: [...], num_trials: 100, annualization_factor: 252 }
      → compute_deflated_sharpe(returns, num_trials, annualization_factor)
      → DeflatedSharpeResponse (HTTP 200)

Example::

    POST /api/v1/metrics/deflated-sharpe
    Content-Type: application/json
    {
        "returns": [0.001, -0.002, 0.003, ...],
        "num_trials": 50,
        "annualization_factor": 252
    }
    →
    {
        "observed_sharpe": 1.42,
        "expected_max_sharpe": 2.51,
        "deflated_sharpe": -1.08,
        "p_value": 0.14,
        "is_significant": false,
        "num_trials": 50,
        "num_returns": 252,
        "skewness": -0.23,
        "kurtosis": 1.04
    }
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, status

from src.api.schemas.metrics import DeflatedSharpeRequest, DeflatedSharpeResponse
from src.metrics.deflated_sharpe import compute_deflated_sharpe
from src.utils.exceptions import InputValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


# ---------------------------------------------------------------------------
# POST /api/v1/metrics/deflated-sharpe
# ---------------------------------------------------------------------------


@router.post(
    "/deflated-sharpe",
    response_model=DeflatedSharpeResponse,
    status_code=status.HTTP_200_OK,
    summary="Compute Deflated Sharpe Ratio",
    description=(
        "Compute the Deflated Sharpe Ratio (DSR) for a return series.  "
        "DSR corrects the observed Sharpe Ratio for multiple-testing bias — "
        "essential when evaluating strategies that were selected from a larger "
        "pool of candidates.  Based on Bailey & Lopez de Prado (2014)."
    ),
)
async def compute_deflated_sharpe_endpoint(
    body: DeflatedSharpeRequest,
) -> DeflatedSharpeResponse:
    """Compute the Deflated Sharpe Ratio for a strategy's return series.

    Validates the request body (Pydantic ensures ``len(returns) >= 10`` and
    ``num_trials >= 1``), then delegates all computation to
    :func:`~src.metrics.deflated_sharpe.compute_deflated_sharpe` which is a
    pure-Python, stateless function (no DB or Redis required).

    Args:
        body: Validated request containing ``returns``, ``num_trials``, and
              ``annualization_factor``.

    Returns:
        :class:`~src.api.schemas.metrics.DeflatedSharpeResponse` with the DSR
        statistic, p-value, significance flag, and all intermediate values.

    Raises:
        :exc:`~src.utils.exceptions.ValidationError`: When ``returns`` contains
            fewer than 10 observations or ``num_trials`` is less than 1 (HTTP 422).

    Example::

        POST /api/v1/metrics/deflated-sharpe
        {
            "returns": [0.001, -0.002, 0.003, ...],  # >= 10 items
            "num_trials": 100
        }
        →  HTTP 200
        {
            "observed_sharpe": 1.42,
            "p_value": 0.14,
            "is_significant": false
        }
    """
    try:
        result = compute_deflated_sharpe(
            returns=body.returns,
            num_trials=body.num_trials,
            annualization_factor=body.annualization_factor,
        )
    except ValueError as exc:
        logger.warning(
            "metrics.deflated_sharpe.invalid_input",
            extra={"error": str(exc), "num_returns": len(body.returns), "num_trials": body.num_trials},
        )
        raise InputValidationError(str(exc)) from exc

    logger.info(
        "metrics.deflated_sharpe.computed",
        extra={
            "num_returns": result.num_returns,
            "num_trials": result.num_trials,
            "observed_sharpe": round(result.observed_sharpe, 4),
            "deflated_sharpe": round(result.deflated_sharpe, 4),
            "p_value": round(result.p_value, 4),
            "is_significant": result.is_significant,
        },
    )

    return DeflatedSharpeResponse(
        observed_sharpe=result.observed_sharpe,
        expected_max_sharpe=result.expected_max_sharpe,
        deflated_sharpe=result.deflated_sharpe,
        p_value=result.p_value,
        is_significant=result.is_significant,
        num_trials=result.num_trials,
        num_returns=result.num_returns,
        skewness=result.skewness,
        kurtosis=result.kurtosis,
    )
