"""Pydantic models for strategy definitions and conditions.

These are domain models used by the strategy service for validation,
not ORM models or API schemas. The strategy definition is persisted
as JSONB in the ``strategy_versions.definition`` column.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d"]

ModelType = Literal["rule_based", "ml", "rl"]


class EntryConditions(BaseModel):
    """All entry conditions — ALL must pass for an entry signal."""

    rsi_below: float | None = Field(default=None, description="RSI must be below this value to enter")
    rsi_above: float | None = Field(default=None, description="RSI must be above this value to enter")
    macd_cross_above: bool | None = Field(default=None, description="MACD line crosses above signal line")
    macd_cross_below: bool | None = Field(default=None, description="MACD line crosses below signal line")
    price_above_sma: int | None = Field(default=None, description="Price must be above SMA of this period")
    price_below_sma: int | None = Field(default=None, description="Price must be below SMA of this period")
    price_above_ema: int | None = Field(default=None, description="Price must be above EMA of this period")
    price_below_ema: int | None = Field(default=None, description="Price must be below EMA of this period")
    bb_below_lower: bool | None = Field(default=None, description="Price below lower Bollinger Band")
    bb_above_upper: bool | None = Field(default=None, description="Price above upper Bollinger Band")
    adx_above: float | None = Field(default=None, description="ADX must be above this value (trend strength)")
    volume_above_ma: float | None = Field(default=None, description="Volume must be above N * volume MA")


class ExitConditions(BaseModel):
    """Exit conditions — ANY triggers an exit."""

    stop_loss_pct: float | None = Field(default=None, ge=0, le=100, description="Stop loss percentage from entry")
    take_profit_pct: float | None = Field(default=None, ge=0, le=1000, description="Take profit percentage from entry")
    trailing_stop_pct: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Trailing stop percentage from peak",
    )
    max_hold_candles: int | None = Field(default=None, ge=1, description="Max candles to hold a position")
    rsi_above: float | None = Field(default=None, description="Exit when RSI rises above this value")
    rsi_below: float | None = Field(default=None, description="Exit when RSI drops below this value")
    macd_cross_below: bool | None = Field(default=None, description="Exit when MACD crosses below signal")


class StrategyDefinition(BaseModel):
    """Complete strategy definition persisted as JSONB."""

    pairs: list[str] = Field(..., min_length=1, description="Trading pairs (e.g. ['BTCUSDT', 'ETHUSDT'])")
    timeframe: Timeframe = Field(default="1h", description="Candle timeframe")
    entry_conditions: EntryConditions = Field(default_factory=EntryConditions)
    exit_conditions: ExitConditions = Field(default_factory=ExitConditions)
    position_size_pct: Decimal = Field(
        default=Decimal("10"),
        ge=Decimal("1"),
        le=Decimal("100"),
        description="Position size as % of equity",
    )
    max_positions: int = Field(default=3, ge=1, le=50, description="Max simultaneous positions")
    filters: dict[str, Any] = Field(default_factory=dict, description="Optional filters (min_volume, etc.)")
    model_type: ModelType = Field(default="rule_based", description="Strategy model type")
    model_reference: str | None = Field(default=None, description="Reference to ML/RL model artifact")

    @model_validator(mode="after")
    def _validate_pairs(self) -> StrategyDefinition:
        """Ensure all pair strings are uppercase and non-empty."""
        self.pairs = [p.upper().strip() for p in self.pairs if p.strip()]
        if not self.pairs:
            raise ValueError("At least one trading pair is required.")
        return self
