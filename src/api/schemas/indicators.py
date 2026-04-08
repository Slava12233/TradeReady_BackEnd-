"""Pydantic v2 request/response schemas for the market indicators endpoints.

Covers the following REST endpoints:
- ``GET /api/v1/market/indicators/available``
- ``GET /api/v1/market/indicators/{symbol}``

Example::

    from src.api.schemas.indicators import IndicatorResponse, AvailableIndicatorsResponse
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared config base
# ---------------------------------------------------------------------------


class _BaseSchema(BaseModel):
    """Base schema with shared Pydantic v2 configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Available indicators  –  GET /market/indicators/available
# ---------------------------------------------------------------------------


class AvailableIndicatorsResponse(_BaseSchema):
    """Response body for ``GET /api/v1/market/indicators/available``.

    Returns the static list of all supported indicator names that the
    :class:`~src.strategies.indicators.IndicatorEngine` can compute.

    Attributes:
        indicators: Alphabetically sorted list of supported indicator names.
    """

    indicators: list[str] = Field(
        ...,
        description="List of all supported indicator names.",
        examples=[["adx_14", "atr_14", "bb_lower", "bb_mid", "bb_upper"]],
    )


# ---------------------------------------------------------------------------
# Computed indicator values  –  GET /market/indicators/{symbol}
# ---------------------------------------------------------------------------


class IndicatorResponse(_BaseSchema):
    """Response body for ``GET /api/v1/market/indicators/{symbol}``.

    Contains the computed indicator values for a given symbol, derived from
    the most recent 1-minute candles stored in TimescaleDB.

    Attributes:
        symbol:       The trading pair symbol (e.g. ``"BTCUSDT"``).
        timestamp:    UTC datetime when the indicators were computed.
        candles_used: Number of 1-minute candles fed into the engine.
        indicators:   Map of indicator name → computed float value. Indicators
                      that could not be computed due to insufficient data are
                      omitted from the dict (not returned as ``null``).
    """

    symbol: str = Field(
        ...,
        description="Trading pair symbol.",
        examples=["BTCUSDT"],
    )
    timestamp: datetime = Field(
        ...,
        description="UTC datetime when the indicators were computed.",
    )
    candles_used: int = Field(
        ...,
        description="Number of 1-minute candles fed into the indicator engine.",
        examples=[200],
    )
    indicators: dict[str, float] = Field(
        ...,
        description=(
            "Map of indicator name to computed float value. Only indicators with valid (non-null) values are included."
        ),
        examples=[
            {
                "rsi_14": 54.32,
                "macd_line": 12.45,
                "sma_20": 64300.12,
                "price": 64521.30,
            }
        ],
    )
