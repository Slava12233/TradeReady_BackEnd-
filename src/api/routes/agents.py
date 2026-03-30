"""Agent management routes for the AI Agent Crypto Trading Platform.

Implements multi-agent CRUD endpoints:

- ``POST   /api/v1/agents``                                          — create agent
- ``GET    /api/v1/agents``                                          — list agents
- ``GET    /api/v1/agents/overview``                                 — all agents with summary
- ``GET    /api/v1/agents/{agent_id}``                               — get agent detail
- ``PUT    /api/v1/agents/{agent_id}``                               — update agent
- ``POST   /api/v1/agents/{agent_id}/clone``                        — clone agent config
- ``POST   /api/v1/agents/{agent_id}/reset``                        — reset agent balances
- ``POST   /api/v1/agents/{agent_id}/archive``                      — archive (soft delete)
- ``DELETE /api/v1/agents/{agent_id}``                              — permanent delete
- ``POST   /api/v1/agents/{agent_id}/regenerate-key``               — regenerate API key
- ``GET    /api/v1/agents/{agent_id}/skill.md``                     — download agent skill file
- ``GET    /api/v1/agents/{agent_id}/decisions/trace/{trace_id}``   — full decision chain replay
- ``GET    /api/v1/agents/{agent_id}/decisions/analyze``            — decision analysis & win stats

All endpoints require JWT authentication (web UI).  The authenticated account
is resolved via :func:`~src.api.middleware.auth.get_current_account`.
"""

from __future__ import annotations

from decimal import Decimal
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import PlainTextResponse

from src.api.middleware.auth import CurrentAccountDep
from src.api.schemas.account import RiskProfileInfo
from src.api.schemas.agents import (
    AgentCreate,
    AgentCredentialsResponse,
    AgentKeyResponse,
    AgentListResponse,
    AgentOverviewResponse,
    AgentResponse,
    AgentUpdate,
    ApiCallItem,
    DecisionAnalysisResponse,
    DecisionItem,
    DecisionTraceResponse,
    DirectionStats,
    FeedbackResponse,
    OrderSummary,
    StrategySignalItem,
    TradeSummary,
    UpdateFeedbackRequest,
)
from src.config import get_settings
from src.database.models import Agent, AgentApiCall, AgentDecision, AgentStrategySignal, Order, Trade
from src.dependencies import AgentDecisionRepoDep, AgentRepoDep, AgentServiceDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_to_response(agent: Agent) -> AgentResponse:
    """Convert an ORM Agent to an AgentResponse schema."""
    api_key_preview = (agent.api_key or "")[:12] + "..." if agent.api_key else "***"
    return AgentResponse(
        id=agent.id,
        account_id=agent.account_id,
        display_name=agent.display_name,
        api_key_preview=api_key_preview,
        starting_balance=Decimal(str(agent.starting_balance)),
        llm_model=agent.llm_model,
        framework=agent.framework,
        strategy_tags=list(agent.strategy_tags) if agent.strategy_tags else [],
        risk_profile=dict(agent.risk_profile) if agent.risk_profile else {},
        avatar_url=agent.avatar_url,
        color=agent.color,
        status=agent.status,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/agents — create agent
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=AgentCredentialsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create agent",
    description="Create a new trading agent with an initial USDT balance.",
)
async def create_agent(
    body: AgentCreate,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> AgentCredentialsResponse:
    """Create a new trading agent for the authenticated account."""
    creds = await agent_service.create_agent(
        account_id=account.id,
        display_name=body.display_name,
        starting_balance=body.starting_balance,
        llm_model=body.llm_model,
        framework=body.framework,
        strategy_tags=body.strategy_tags,
        risk_profile=body.risk_profile,
        color=body.color,
    )

    logger.info(
        "agents.created",
        extra={"account_id": str(account.id), "agent_id": str(creds.agent_id)},
    )

    return AgentCredentialsResponse(
        agent_id=creds.agent_id,
        api_key=creds.api_key,
        display_name=creds.display_name,
        starting_balance=creds.starting_balance,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/agents — list agents
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=AgentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List agents",
    description="List all agents for the authenticated account.",
)
async def list_agents(
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
    include_archived: bool = Query(default=False, description="Include archived agents."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AgentListResponse:
    """List agents owned by the authenticated account."""
    agents = await agent_service.list_agents(
        account.id,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )

    return AgentListResponse(
        agents=[_agent_to_response(a) for a in agents],
        total=len(agents),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/agents/overview — all agents with summary
# ---------------------------------------------------------------------------


@router.get(
    "/overview",
    response_model=AgentOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Agent overview",
    description="Return all active agents with summary data.",
)
async def agent_overview(
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> AgentOverviewResponse:
    """Return all active agents for the authenticated account."""
    agents = await agent_service.list_agents(account.id, include_archived=False)
    return AgentOverviewResponse(
        agents=[_agent_to_response(a) for a in agents],
    )


# ---------------------------------------------------------------------------
# GET /api/v1/agents/{agent_id} — get agent detail
# ---------------------------------------------------------------------------


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get agent",
    description="Get details for a specific agent.",
)
async def get_agent(
    agent_id: UUID,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> AgentResponse:
    """Get a specific agent owned by the authenticated account."""
    agent = await agent_service.get_agent(agent_id)
    if agent.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError

        raise PermissionDeniedError("You do not own this agent.")
    return _agent_to_response(agent)


# ---------------------------------------------------------------------------
# PUT /api/v1/agents/{agent_id} — update agent
# ---------------------------------------------------------------------------


@router.put(
    "/{agent_id}",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update agent",
    description="Update an agent's configuration.",
)
async def update_agent(
    agent_id: UUID,
    body: AgentUpdate,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> AgentResponse:
    """Update fields on an agent owned by the authenticated account."""
    update_data = body.model_dump(exclude_unset=True)
    agent = await agent_service.update_agent(agent_id, account.id, **update_data)
    return _agent_to_response(agent)


# ---------------------------------------------------------------------------
# POST /api/v1/agents/{agent_id}/clone — clone agent
# ---------------------------------------------------------------------------


@router.post(
    "/{agent_id}/clone",
    response_model=AgentCredentialsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Clone agent",
    description="Clone an agent's configuration into a new agent.",
)
async def clone_agent(
    agent_id: UUID,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
    new_name: str | None = Query(default=None, description="Name for the clone."),
) -> AgentCredentialsResponse:
    """Clone an agent's configuration into a new agent."""
    creds = await agent_service.clone_agent(agent_id, account.id, new_name=new_name)
    return AgentCredentialsResponse(
        agent_id=creds.agent_id,
        api_key=creds.api_key,
        display_name=creds.display_name,
        starting_balance=creds.starting_balance,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/agents/{agent_id}/reset — reset agent
# ---------------------------------------------------------------------------


@router.post(
    "/{agent_id}/reset",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset agent",
    description="Reset an agent's balances to starting balance.",
)
async def reset_agent(
    agent_id: UUID,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> AgentResponse:
    """Reset an agent's balances and start fresh."""
    agent = await agent_service.reset_agent(agent_id, account.id)
    return _agent_to_response(agent)


# ---------------------------------------------------------------------------
# POST /api/v1/agents/{agent_id}/archive — archive agent
# ---------------------------------------------------------------------------


@router.post(
    "/{agent_id}/archive",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive agent",
    description="Archive an agent (soft delete).",
)
async def archive_agent(
    agent_id: UUID,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> AgentResponse:
    """Archive an agent (soft delete)."""
    agent = await agent_service.archive_agent(agent_id, account.id)
    return _agent_to_response(agent)


# ---------------------------------------------------------------------------
# DELETE /api/v1/agents/{agent_id} — permanent delete
# ---------------------------------------------------------------------------


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete agent",
    description="Permanently delete an agent and all associated data.",
    response_class=Response,
)
async def delete_agent(
    agent_id: UUID,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> Response:
    """Permanently delete an agent."""
    await agent_service.delete_agent(agent_id, account.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# GET /api/v1/agents/{agent_id}/api-key — reveal full API key
# ---------------------------------------------------------------------------


@router.get(
    "/{agent_id}/api-key",
    response_model=AgentKeyResponse,
    status_code=status.HTTP_200_OK,
    summary="Get agent API key",
    description="Return the full plaintext API key for an agent. JWT auth + ownership required.",
)
async def get_agent_api_key(
    agent_id: UUID,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> AgentKeyResponse:
    """Return the full API key for an agent owned by the authenticated account."""
    agent = await agent_service.get_agent(agent_id)
    if agent.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this agent.")
    return AgentKeyResponse(
        agent_id=agent_id,
        api_key=agent.api_key or "",
        message="Current API key for this agent.",
    )


# ---------------------------------------------------------------------------
# POST /api/v1/agents/{agent_id}/regenerate-key — regenerate API key
# ---------------------------------------------------------------------------


@router.post(
    "/{agent_id}/regenerate-key",
    response_model=AgentKeyResponse,
    status_code=status.HTTP_200_OK,
    summary="Regenerate API key",
    description="Generate a new API key for the agent. The old key is invalidated.",
)
async def regenerate_key(
    agent_id: UUID,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> AgentKeyResponse:
    """Regenerate the API key for an agent."""
    new_key = await agent_service.regenerate_api_key(agent_id, account.id)
    return AgentKeyResponse(
        agent_id=agent_id,
        api_key=new_key,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/agents/{agent_id}/risk-profile — get agent risk profile
# ---------------------------------------------------------------------------

# Default risk profile values (used when risk_profile JSONB is empty/missing)
_DEFAULT_MAX_POSITION_PCT = 25
_DEFAULT_DAILY_LOSS_PCT = 20
_DEFAULT_MAX_OPEN_ORDERS = 50


@router.get(
    "/{agent_id}/risk-profile",
    response_model=RiskProfileInfo,
    status_code=status.HTTP_200_OK,
    summary="Get agent risk profile",
    description="Return the effective risk limits for a specific agent.",
)
async def get_agent_risk_profile(
    agent_id: UUID,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> RiskProfileInfo:
    """Return the effective risk profile for an agent."""
    agent = await agent_service.get_agent(agent_id)
    if agent.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this agent.")

    profile: dict[str, Any] = dict(agent.risk_profile) if agent.risk_profile else {}
    return RiskProfileInfo(
        max_position_size_pct=int(profile.get("max_position_size_pct", _DEFAULT_MAX_POSITION_PCT)),
        daily_loss_limit_pct=int(profile.get("daily_loss_limit_pct", _DEFAULT_DAILY_LOSS_PCT)),
        max_open_orders=int(profile.get("max_open_orders", _DEFAULT_MAX_OPEN_ORDERS)),
    )


# ---------------------------------------------------------------------------
# PUT /api/v1/agents/{agent_id}/risk-profile — update agent risk profile
# ---------------------------------------------------------------------------


@router.put(
    "/{agent_id}/risk-profile",
    response_model=RiskProfileInfo,
    status_code=status.HTTP_200_OK,
    summary="Update agent risk profile",
    description="Update the risk limits for a specific agent.",
)
async def update_agent_risk_profile(
    agent_id: UUID,
    body: RiskProfileInfo,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
    agent_repo: AgentRepoDep,
) -> RiskProfileInfo:
    """Update the risk profile for an agent."""
    agent = await agent_service.get_agent(agent_id)
    if agent.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this agent.")

    # Merge new risk settings into existing profile
    profile: dict[str, Any] = dict(agent.risk_profile) if agent.risk_profile else {}
    profile["max_position_size_pct"] = body.max_position_size_pct
    profile["daily_loss_limit_pct"] = body.daily_loss_limit_pct
    profile["max_open_orders"] = body.max_open_orders

    await agent_repo.update(agent_id, risk_profile=profile)

    logger.info(
        "agents.risk_profile_updated",
        extra={"account_id": str(account.id), "agent_id": str(agent_id)},
    )

    return body


# ---------------------------------------------------------------------------
# GET /api/v1/agents/{agent_id}/skill.md — download agent skill file
# ---------------------------------------------------------------------------


@router.get(
    "/{agent_id}/skill.md",
    response_class=PlainTextResponse,
    status_code=status.HTTP_200_OK,
    summary="Download agent skill file",
    description="Download a skill.md file with the agent's API key injected.",
)
async def get_agent_skill_md(
    agent_id: UUID,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> PlainTextResponse:
    """Return a skill.md file customised with the agent's API key."""
    agent = await agent_service.get_agent(agent_id)
    if agent.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError

        raise PermissionDeniedError("You do not own this agent.")

    settings = get_settings()
    base_url = settings.api_base_url if hasattr(settings, "api_base_url") else "http://localhost:8000"

    # Read the template skill.md
    from pathlib import Path  # noqa: PLC0415

    skill_path = Path(__file__).resolve().parents[3] / "docs" / "skill.md"
    try:
        template = skill_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        template = _DEFAULT_SKILL_TEMPLATE

    # Inject agent-specific values
    api_key_preview = (agent.api_key or "")[:12] + "..." if agent.api_key else "YOUR_API_KEY"
    content = template.replace("YOUR_API_KEY", api_key_preview)
    content = content.replace("http://localhost:8000/api/v1", f"{base_url}/api/v1")

    # Add agent header
    agent_header = f"# Agent: {agent.display_name}\n# Agent ID: {agent.id}\n# API Key: {api_key_preview}\n\n"
    content = agent_header + content

    return PlainTextResponse(content, media_type="text/markdown")


# ---------------------------------------------------------------------------
# Helpers — decision trace & analysis serialisers
# ---------------------------------------------------------------------------


def _decision_to_item(decision: AgentDecision) -> DecisionItem:
    """Convert an ORM AgentDecision to a DecisionItem schema."""
    return DecisionItem(
        id=decision.id,
        agent_id=decision.agent_id,
        trace_id=decision.trace_id,
        decision_type=decision.decision_type,
        symbol=decision.symbol,
        direction=decision.direction,
        confidence=Decimal(str(decision.confidence)) if decision.confidence is not None else None,
        reasoning=decision.reasoning,
        market_snapshot=dict(decision.market_snapshot) if decision.market_snapshot else None,
        risk_assessment=dict(decision.risk_assessment) if decision.risk_assessment else None,
        order_id=decision.order_id,
        outcome_pnl=Decimal(str(decision.outcome_pnl)) if decision.outcome_pnl is not None else None,
        outcome_recorded_at=decision.outcome_recorded_at,
        created_at=decision.created_at,
    )


def _signal_to_item(signal: AgentStrategySignal) -> StrategySignalItem:
    """Convert an ORM AgentStrategySignal to a StrategySignalItem schema."""
    return StrategySignalItem(
        id=signal.id,
        trace_id=signal.trace_id,
        strategy_name=signal.strategy_name,
        symbol=signal.symbol,
        action=signal.action,
        confidence=Decimal(str(signal.confidence)) if signal.confidence is not None else None,
        weight=Decimal(str(signal.weight)) if signal.weight is not None else None,
        signal_data=dict(signal.signal_data) if signal.signal_data else {},
        created_at=signal.created_at,
    )


def _api_call_to_item(call: AgentApiCall) -> ApiCallItem:
    """Convert an ORM AgentApiCall to an ApiCallItem schema."""
    return ApiCallItem(
        id=call.id,
        trace_id=call.trace_id,
        channel=call.channel,
        endpoint=call.endpoint,
        method=call.method,
        status_code=call.status_code,
        latency_ms=Decimal(str(call.latency_ms)),
        request_size=call.request_size,
        response_size=call.response_size,
        error=call.error,
        created_at=call.created_at,
    )


def _order_to_summary(order: Order) -> OrderSummary:
    """Convert an ORM Order to an OrderSummary schema."""
    return OrderSummary(
        id=order.id,
        symbol=order.symbol,
        side=order.side,
        type=order.type,
        quantity=Decimal(str(order.quantity)),
        executed_price=Decimal(str(order.executed_price)) if order.executed_price is not None else None,
        executed_qty=Decimal(str(order.executed_qty)) if order.executed_qty is not None else None,
        fee=Decimal(str(order.fee)) if order.fee is not None else None,
        status=order.status,
        created_at=order.created_at,
        filled_at=order.filled_at,
    )


def _trade_to_summary(trade: Trade) -> TradeSummary:
    """Convert an ORM Trade to a TradeSummary schema."""
    return TradeSummary(
        id=trade.id,
        symbol=trade.symbol,
        side=trade.side,
        quantity=Decimal(str(trade.quantity)),
        price=Decimal(str(trade.price)),
        quote_amount=Decimal(str(trade.quote_amount)),
        fee=Decimal(str(trade.fee)),
        realized_pnl=Decimal(str(trade.realized_pnl)) if trade.realized_pnl is not None else None,
        created_at=trade.created_at,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/agents/{agent_id}/decisions/trace/{trace_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{agent_id}/decisions/trace/{trace_id}",
    response_model=DecisionTraceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get decision trace",
    description=(
        "Return the full decision chain for a single trace ID: strategy signals, "
        "the fused decision, outbound API calls, and (if executed) the order and trade fill."
    ),
)
async def get_decision_trace(
    agent_id: UUID,
    trace_id: str,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
    decision_repo: AgentDecisionRepoDep,
) -> DecisionTraceResponse:
    """Return the full decision chain for a trace ID owned by the authenticated account."""
    from sqlalchemy import select  # noqa: PLC0415

    # Ownership check — agent must belong to authenticated account.
    agent = await agent_service.get_agent(agent_id)
    if agent.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this agent.")

    # 1. Strategy signals for this trace (no agent_id filter in signal repo).
    signal_rows = await decision_repo._session.execute(
        select(AgentStrategySignal)
        .where(AgentStrategySignal.trace_id == trace_id)
        .order_by(AgentStrategySignal.created_at.asc())
    )
    signals = [_signal_to_item(s) for s in signal_rows.scalars().all()]

    # 2. Decision for this agent + trace.
    decision_orm = await decision_repo.get_by_trace(agent_id, trace_id)
    decision_item = _decision_to_item(decision_orm) if decision_orm is not None else None

    # 3. API calls for this agent + trace.
    api_call_rows = await decision_repo._session.execute(
        select(AgentApiCall)
        .where(
            AgentApiCall.agent_id == agent_id,
            AgentApiCall.trace_id == trace_id,
        )
        .order_by(AgentApiCall.created_at.asc())
    )
    api_calls = [_api_call_to_item(c) for c in api_call_rows.scalars().all()]

    # 4. If decision has an order_id, fetch the order and its first trade fill.
    order_summary: OrderSummary | None = None
    trade_summary: TradeSummary | None = None
    pnl_str: str | None = None

    if decision_orm is not None and decision_orm.order_id is not None:
        order_row = await decision_repo._session.execute(select(Order).where(Order.id == decision_orm.order_id))
        order_orm = order_row.scalars().first()
        if order_orm is not None:
            order_summary = _order_to_summary(order_orm)

            # Fetch the most recent trade fill for this order (there is typically one).
            trade_row = await decision_repo._session.execute(
                select(Trade).where(Trade.order_id == decision_orm.order_id).order_by(Trade.created_at.desc()).limit(1)
            )
            trade_orm = trade_row.scalars().first()
            if trade_orm is not None:
                trade_summary = _trade_to_summary(trade_orm)

        # Surface outcome PnL at the top level for quick access.
        if decision_orm.outcome_pnl is not None:
            pnl_str = str(decision_orm.outcome_pnl)

    logger.info(
        "agents.decision_trace.fetched",
        extra={
            "account_id": str(account.id),
            "agent_id": str(agent_id),
            "trace_id": trace_id,
            "signal_count": len(signals),
            "api_call_count": len(api_calls),
        },
    )

    return DecisionTraceResponse(
        trace_id=trace_id,
        signals=signals,
        decision=decision_item,
        api_calls=api_calls,
        order=order_summary,
        trade=trade_summary,
        pnl=pnl_str,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/agents/{agent_id}/decisions/analyze
# ---------------------------------------------------------------------------

_MAX_ANALYZE_LIMIT = 500


@router.get(
    "/{agent_id}/decisions/analyze",
    response_model=DecisionAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze agent decisions",
    description=(
        "Return aggregate win/loss statistics and the filtered decision list for an agent. "
        "Supports filtering by time range, minimum confidence, direction, and PnL outcome."
    ),
)
async def analyze_decisions(
    agent_id: UUID,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
    decision_repo: AgentDecisionRepoDep,
    start: str | None = Query(
        default=None,
        description="ISO-8601 UTC lower bound for created_at (inclusive).",
        examples=["2026-01-01T00:00:00Z"],
    ),
    end: str | None = Query(
        default=None,
        description="ISO-8601 UTC upper bound for created_at (exclusive).",
        examples=["2026-02-01T00:00:00Z"],
    ),
    min_confidence: float | None = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description="Only include decisions with confidence >= this value.",
        examples=[0.5],
    ),
    direction: str | None = Query(
        default=None,
        description="Filter by trade direction: 'buy', 'sell', or 'hold'.",
        examples=["buy"],
    ),
    pnl_outcome: str | None = Query(
        default="all",
        description="Filter by PnL outcome: 'positive', 'negative', or 'all' (default).",
        examples=["positive"],
    ),
    limit: int = Query(
        default=200,
        ge=1,
        le=_MAX_ANALYZE_LIMIT,
        description="Maximum number of decision rows to return (1–500).",
    ),
) -> DecisionAnalysisResponse:
    """Analyze decisions for an agent with filtering and aggregate statistics."""
    from datetime import UTC, datetime  # noqa: PLC0415

    from src.utils.exceptions import InputValidationError  # noqa: PLC0415

    # Ownership check.
    agent = await agent_service.get_agent(agent_id)
    if agent.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this agent.")

    # Parse datetime params.
    start_dt: datetime | None = None
    end_dt: datetime | None = None
    try:
        if start is not None:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(UTC)
        if end is not None:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise InputValidationError(f"Invalid datetime format: {exc}") from exc

    # Validate direction.
    if direction is not None and direction not in ("buy", "sell", "hold"):
        raise InputValidationError("direction must be one of: 'buy', 'sell', 'hold'.")

    # Validate pnl_outcome.
    if pnl_outcome not in (None, "positive", "negative", "all"):
        raise InputValidationError("pnl_outcome must be one of: 'positive', 'negative', 'all'.")

    min_conf_dec = Decimal(str(min_confidence)) if min_confidence is not None else None
    effective_pnl_outcome = pnl_outcome if pnl_outcome != "all" else None

    decisions = await decision_repo.analyze(
        agent_id,
        start=start_dt,
        end=end_dt,
        min_confidence=min_conf_dec,
        direction=direction,
        pnl_outcome=effective_pnl_outcome,
        limit=limit,
    )

    # Compute aggregate statistics.
    total = len(decisions)
    wins = sum(1 for d in decisions if d.outcome_pnl is not None and d.outcome_pnl > 0)
    losses = sum(1 for d in decisions if d.outcome_pnl is not None and d.outcome_pnl < 0)
    win_rate = wins / total if total > 0 else 0.0

    # Average PnL (only over decisions that have an outcome recorded).
    resolved = [d for d in decisions if d.outcome_pnl is not None]
    avg_pnl_str: str | None = None
    if resolved:
        total_pnl = sum(Decimal(str(d.outcome_pnl)) for d in resolved)
        avg_pnl_str = str(total_pnl / len(resolved))

    # Average confidence.
    confident = [d for d in decisions if d.confidence is not None]
    avg_conf_str: str | None = None
    if confident:
        total_conf = sum(Decimal(str(d.confidence)) for d in confident)
        avg_conf_str = str(total_conf / len(confident))

    # Per-direction breakdown.
    all_directions = {d.direction for d in decisions}
    by_direction: dict[str, DirectionStats] = {}
    for dir_val in sorted(all_directions):
        dir_decisions = [d for d in decisions if d.direction == dir_val]
        dir_total = len(dir_decisions)
        dir_wins = sum(1 for d in dir_decisions if d.outcome_pnl is not None and d.outcome_pnl > 0)
        dir_losses = sum(1 for d in dir_decisions if d.outcome_pnl is not None and d.outcome_pnl < 0)
        dir_win_rate = dir_wins / dir_total if dir_total > 0 else 0.0

        dir_resolved = [d for d in dir_decisions if d.outcome_pnl is not None]
        dir_avg_pnl: str | None = None
        if dir_resolved:
            dir_total_pnl = sum(Decimal(str(d.outcome_pnl)) for d in dir_resolved)
            dir_avg_pnl = str(dir_total_pnl / len(dir_resolved))

        dir_confident = [d for d in dir_decisions if d.confidence is not None]
        dir_avg_conf: str | None = None
        if dir_confident:
            dir_total_conf = sum(Decimal(str(d.confidence)) for d in dir_confident)
            dir_avg_conf = str(dir_total_conf / len(dir_confident))

        by_direction[dir_val] = DirectionStats(
            total=dir_total,
            wins=dir_wins,
            losses=dir_losses,
            win_rate=dir_win_rate,
            avg_pnl=dir_avg_pnl,
            avg_confidence=dir_avg_conf,
        )

    decision_items = [_decision_to_item(d) for d in decisions]

    logger.info(
        "agents.decisions.analyzed",
        extra={
            "account_id": str(account.id),
            "agent_id": str(agent_id),
            "total": total,
            "wins": wins,
            "losses": losses,
        },
    )

    return DecisionAnalysisResponse(
        total=total,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        avg_pnl=avg_pnl_str,
        avg_confidence=avg_conf_str,
        by_direction=by_direction,
        decisions=decision_items,
    )


# ---------------------------------------------------------------------------
# PATCH /api/v1/agents/{agent_id}/feedback/{feedback_id} — update feedback
# ---------------------------------------------------------------------------


@router.patch(
    "/{agent_id}/feedback/{feedback_id}",
    response_model=FeedbackResponse,
    status_code=status.HTTP_200_OK,
    summary="Update feedback status",
    description=(
        "Update the lifecycle status of a feedback item. "
        "Only the owning account can update its agent's feedback. "
        "Sets ``resolved_at`` automatically when status is set to ``resolved``."
    ),
)
async def update_feedback(
    agent_id: UUID,
    feedback_id: UUID,
    body: UpdateFeedbackRequest,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> FeedbackResponse:
    """Update the lifecycle status (and optional resolution) for a feedback item.

    Args:
        agent_id:    UUID of the agent that raised the feedback.
        feedback_id: UUID of the feedback row to update.
        body:        New status and optional resolution text.
        account:     Authenticated account (from JWT middleware).
        agent_service: Injected agent service for ownership lookup.

    Returns:
        FeedbackResponse with the updated status, resolution, and resolved_at.

    Raises:
        PermissionDeniedError: If the authenticated account does not own the agent.
        ResourceNotFoundError: If the feedback row does not exist.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy import update as sa_update

    from src.database.models import AgentFeedback  # noqa: PLC0415
    from src.database.session import get_session_factory  # noqa: PLC0415
    from src.utils.exceptions import PermissionDeniedError, TradingPlatformError  # noqa: PLC0415

    # Ownership check — agent must belong to authenticated account.
    agent = await agent_service.get_agent(agent_id)
    if agent.account_id != account.id:
        raise PermissionDeniedError("You do not own this agent.")

    factory = get_session_factory()
    now = datetime.now(UTC)
    resolved_at_value: datetime | None = now if body.status == "resolved" else None

    async with factory() as session:
        # Fetch the feedback row — verify it belongs to this agent.
        result = await session.execute(
            select(AgentFeedback).where(
                AgentFeedback.id == feedback_id,
                AgentFeedback.agent_id == agent_id,
            )
        )
        feedback = result.scalars().first()
        if feedback is None:
            raise TradingPlatformError(
                message=f"Feedback {feedback_id} not found.",
                code="FEEDBACK_NOT_FOUND",
                http_status=404,
            )

        # Build update payload.
        update_values: dict[str, object] = {"status": body.status}
        if body.resolution is not None:
            update_values["resolution"] = body.resolution
        if resolved_at_value is not None:
            update_values["resolved_at"] = resolved_at_value

        await session.execute(sa_update(AgentFeedback).where(AgentFeedback.id == feedback_id).values(**update_values))
        await session.commit()

        # Re-fetch to return the current persisted state.
        refreshed = await session.execute(select(AgentFeedback).where(AgentFeedback.id == feedback_id))
        updated_feedback = refreshed.scalars().first()

    logger.info(
        "agents.feedback.updated",
        extra={
            "account_id": str(account.id),
            "agent_id": str(agent_id),
            "feedback_id": str(feedback_id),
            "new_status": body.status,
        },
    )

    assert updated_feedback is not None  # noqa: S101 — row was confirmed to exist above
    return FeedbackResponse(
        id=updated_feedback.id,
        agent_id=updated_feedback.agent_id,
        status=updated_feedback.status,
        resolution=updated_feedback.resolution,
        resolved_at=updated_feedback.resolved_at,
        updated=True,
    )


_DEFAULT_SKILL_TEMPLATE = """# AgentExchange — AI Crypto Trading Platform

You have access to a simulated cryptocurrency exchange powered by real-time market data from Binance.

**Base URL:** `http://localhost:8000/api/v1`

**Authentication:** Include this header in EVERY request:
```
X-API-Key: YOUR_API_KEY
```

**Your first 3 actions should be:**
1. Check your balance → `GET /account/balance`
2. Check a price → `GET /market/price/BTCUSDT`
3. Buy something → `POST /trade/order` with `{"symbol":"BTCUSDT","side":"buy","type":"market","quantity":"0.01"}`
"""
