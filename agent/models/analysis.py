"""Market and backtest analysis output models for the TradeReady Platform Testing Agent."""

from pydantic import BaseModel, ConfigDict, Field


class MarketAnalysis(BaseModel):
    """Structured market analysis produced after reviewing OHLCV candle data.

    Used as ``output_type`` on analysis agents to capture a structured view of
    market conditions for a single trading pair at a point in time.  Price
    levels are stored as strings to preserve precision without introducing
    float rounding errors in JSON serialisation.

    Attributes:
        symbol: The trading pair that was analysed (e.g. ``"BTCUSDT"``).
        trend: Overall market direction: ``"bullish"``, ``"bearish"``, or
            ``"neutral"``.
        support_level: Key support price level expressed as a string
            (e.g. ``"62500.00"``).  String type avoids float precision loss.
        resistance_level: Key resistance price level expressed as a string
            (e.g. ``"65000.00"``).  String type avoids float precision loss.
        indicators: Raw indicator values computed by the agent, keyed by
            indicator name.  Values may be ``float``, ``str``, or nested
            dicts depending on the indicator (e.g. MACD returns a dict of
            ``{"macd": ..., "signal": ..., "hist": ...}``).
        summary: Plain-language synthesis of the analysis suitable for use
            in the agent's reasoning chain or a human-readable report.

    Example::

        analysis = MarketAnalysis(
            symbol="ETHUSDT",
            trend="bullish",
            support_level="2900.00",
            resistance_level="3200.00",
            indicators={"rsi_14": 58.3, "sma_20": 3050.12},
            summary="ETH holding above 20-SMA with RSI in healthy territory.",
        )
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading pair that was analysed.")
    trend: str = Field(
        ...,
        description="Overall market direction: 'bullish', 'bearish', or 'neutral'.",
    )
    support_level: str = Field(
        ...,
        description="Key support price as a string to preserve decimal precision.",
    )
    resistance_level: str = Field(
        ...,
        description="Key resistance price as a string to preserve decimal precision.",
    )
    indicators: dict = Field(
        default_factory=dict,
        description="Computed indicator values keyed by indicator name.",
    )
    summary: str = Field(..., description="Plain-language synthesis of the analysis.")


class BacktestAnalysis(BaseModel):
    """Structured analysis of a completed backtest session.

    Produced after the agent runs a full backtest lifecycle (create → trade
    in sandbox → step to completion → fetch results) and evaluates the
    outcome.  Used as ``output_type`` on backtest analysis agents.

    Attributes:
        session_id: Platform-assigned UUID of the backtest session.
        sharpe_ratio: Annualised Sharpe ratio from the backtest results.
            ``float`` is appropriate here because this is a dimensionless
            ratio, not a monetary value.
        max_drawdown: Maximum peak-to-trough equity decline as a fraction
            (e.g. ``0.12`` for a 12 % drawdown).
        win_rate: Fraction of trades that were profitable, in ``[0.0, 1.0]``.
        total_trades: Total number of round-trip trades executed during the
            backtest session.
        pnl: Realised profit/loss expressed as a string to preserve Decimal
            precision (e.g. ``"243.57"``).  The caller is responsible for
            converting to ``Decimal`` before using in arithmetic.
        improvement_plan: Ordered list of concrete actions the agent proposes
            to improve performance in the next iteration (e.g. tightening
            stop-losses, changing entry signals, etc.).

    Example::

        analysis = BacktestAnalysis(
            session_id="a1b2c3d4-...",
            sharpe_ratio=1.42,
            max_drawdown=0.08,
            win_rate=0.61,
            total_trades=34,
            pnl="182.40",
            improvement_plan=["Tighten stop-loss to 1.5 %", "Add volume filter to entries"],
        )
    """

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(..., description="Platform UUID of the backtest session.")
    sharpe_ratio: float = Field(
        ...,
        description="Annualised Sharpe ratio (dimensionless; float is appropriate).",
    )
    max_drawdown: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Maximum peak-to-trough equity decline as a fraction.",
    )
    win_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of trades that were profitable.",
    )
    total_trades: int = Field(..., ge=0, description="Total round-trip trades executed.")
    pnl: str = Field(
        ...,
        description="Realised PnL as a string to preserve Decimal precision.",
    )
    improvement_plan: list[str] = Field(
        default_factory=list,
        description="Ordered list of concrete improvement actions for the next iteration.",
    )
