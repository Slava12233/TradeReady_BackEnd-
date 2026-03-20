"""Trade signal output model for the TradeReady Platform Testing Agent."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SignalType(str, Enum):
    """Enumeration of possible trade signal directions.

    Inherits from ``str`` so values serialize as plain strings in JSON,
    making them compatible with Pydantic AI ``output_type`` contracts and
    any downstream JSON consumer without extra coercion.
    """

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class TradeSignal(BaseModel):
    """Structured trade decision produced by the agent after market analysis.

    This model is used as ``output_type`` on trading-related Pydantic AI
    agents.  All fields are required so that the LLM is forced to commit to
    every dimension of the decision rather than leaving gaps.

    Attributes:
        symbol: The trading pair the signal applies to (e.g. ``"BTCUSDT"``).
        signal: The directional action to take: buy, sell, or hold.
        confidence: Agent's certainty in the signal, expressed as a fraction
            in the range ``[0.0, 1.0]``.  Values below ``0.5`` typically
            indicate a weak or uncertain signal.
        quantity_pct: Fraction of available equity to allocate to this trade.
            Clamped to ``[0.01, 0.10]`` to respect the platform's 10 %
            per-trade risk cap.
        reasoning: Human-readable explanation of why the signal was generated,
            including the market signals and logic chain the agent used.
        risk_notes: Potential adverse scenarios or risks the agent identified
            that could invalidate the signal.

    Example::

        signal = TradeSignal(
            symbol="BTCUSDT",
            signal=SignalType.BUY,
            confidence=0.72,
            quantity_pct=0.04,
            reasoning="20-period SMA crossed above 50-period SMA with rising volume.",
            risk_notes="FOMC announcement in 2 h could reverse momentum.",
        )
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading pair symbol, e.g. 'BTCUSDT'.")
    signal: SignalType = Field(..., description="Directional action: buy, sell, or hold.")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Agent confidence in the signal, from 0.0 (none) to 1.0 (certain).",
    )
    quantity_pct: float = Field(
        ...,
        ge=0.01,
        le=0.10,
        description="Fraction of equity to use (1 %–10 %).",
    )
    reasoning: str = Field(..., description="Why this trade was decided.")
    risk_notes: str = Field(..., description="Risks that could invalidate this signal.")
