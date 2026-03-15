"""Agent management routes for the AI Agent Crypto Trading Platform.

Implements multi-agent CRUD endpoints:

- ``POST   /api/v1/agents``                          — create agent
- ``GET    /api/v1/agents``                           — list agents
- ``GET    /api/v1/agents/overview``                  — all agents with summary
- ``GET    /api/v1/agents/{agent_id}``                — get agent detail
- ``PUT    /api/v1/agents/{agent_id}``                — update agent
- ``POST   /api/v1/agents/{agent_id}/clone``          — clone agent config
- ``POST   /api/v1/agents/{agent_id}/reset``          — reset agent balances
- ``POST   /api/v1/agents/{agent_id}/archive``        — archive (soft delete)
- ``DELETE /api/v1/agents/{agent_id}``                — permanent delete
- ``POST   /api/v1/agents/{agent_id}/regenerate-key`` — regenerate API key
- ``GET    /api/v1/agents/{agent_id}/skill.md``       — download agent skill file

All endpoints require JWT authentication (web UI).  The authenticated account
is resolved via :func:`~src.api.middleware.auth.get_current_account`.
"""

from __future__ import annotations

from decimal import Decimal
import logging
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import PlainTextResponse

from src.api.middleware.auth import CurrentAccountDep
from src.api.schemas.agents import (
    AgentCreate,
    AgentCredentialsResponse,
    AgentKeyResponse,
    AgentListResponse,
    AgentOverviewResponse,
    AgentResponse,
    AgentUpdate,
)
from src.config import get_settings
from src.database.models import Agent
from src.dependencies import AgentServiceDep

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
)
async def delete_agent(
    agent_id: UUID,
    account: CurrentAccountDep,
    agent_service: AgentServiceDep,
) -> None:
    """Permanently delete an agent."""
    await agent_service.delete_agent(agent_id, account.id)


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
    agent_header = (
        f"# Agent: {agent.display_name}\n"
        f"# Agent ID: {agent.id}\n"
        f"# API Key: {api_key_preview}\n\n"
    )
    content = agent_header + content

    return PlainTextResponse(content, media_type="text/markdown")


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
