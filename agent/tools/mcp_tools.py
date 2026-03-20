"""MCP server factory for the TradeReady Platform Testing Agent.

Provides a single factory function that creates a :class:`pydantic_ai.mcp.MCPServerStdio`
instance configured to launch ``python -m src.mcp.server`` as a subprocess.  The
subprocess communicates with a Pydantic AI agent over stdio using the MCP JSON-RPC
protocol and exposes all 58 trading tools registered by the platform MCP server.

Usage example::

    from pydantic_ai import Agent
    from agent.config import AgentConfig
    from agent.tools.mcp_tools import get_mcp_server

    config = AgentConfig()
    mcp_server = get_mcp_server(config)

    agent = Agent(
        model=config.agent_model,
        mcp_servers=[mcp_server],
    )

    async with agent.run_mcp_servers():
        result = await agent.run("Check the current BTCUSDT price.")
        print(result.output)

Notes:
    - The subprocess **must** be started from the project root (``config.platform_root``)
      so that ``python -m src.mcp.server`` resolves on ``sys.path``.
    - All MCP server logging is emitted to **stderr** only.  stdout is owned by the
      MCP JSON-RPC transport; any stray stdout output will corrupt the session.
    - ``MCP_API_KEY`` is mandatory for the MCP server — it calls ``sys.exit(1)`` if
      missing.  :func:`get_mcp_server` raises :class:`ValueError` early if the config
      has no ``platform_api_key``.
    - Pass ``MCP_JWT_TOKEN`` via config when the agent needs access to JWT-only
      endpoints such as ``/api/v1/agents`` and ``/api/v1/battles``.
"""

import os
import sys

from pydantic_ai.mcp import MCPServerStdio

from agent.config import AgentConfig


def get_mcp_server(config: AgentConfig) -> MCPServerStdio:
    """Create an :class:`~pydantic_ai.mcp.MCPServerStdio` for the TradeReady platform.

    Spawns ``python -m src.mcp.server`` as a child process with the current Python
    interpreter.  The child process is started in the project root directory
    (``config.platform_root``) so that the ``src`` package is importable without any
    ``PYTHONPATH`` manipulation.

    The environment dict is built by overlaying the required MCP variables on top of
    the current process environment (``os.environ``), which ensures that the subprocess
    inherits ``PATH``, virtual-environment binaries, ``PYTHONPATH``, and any other
    variables already present in the shell.

    Args:
        config: Fully-populated :class:`~agent.config.AgentConfig` instance.  The
            following fields are consumed:

            - ``platform_api_key`` — sent as ``MCP_API_KEY`` to the subprocess.
              Must be a non-empty ``ak_live_...`` key.
            - ``platform_base_url`` — sent as ``API_BASE_URL`` so the MCP server
              targets the correct platform instance.
            - ``platform_root`` — used as the subprocess ``cwd``; computed automatically
              from the location of ``agent/config.py``.

    Returns:
        A configured :class:`~pydantic_ai.mcp.MCPServerStdio` instance ready to be
        passed to :class:`pydantic_ai.Agent` via its ``mcp_servers`` parameter.

    Raises:
        ValueError: If ``config.platform_api_key`` is empty or not set, because the
            MCP server subprocess will immediately exit with code 1 without a key.

    Example::

        config = AgentConfig()
        mcp_server = get_mcp_server(config)

        agent = Agent(model=config.agent_model, mcp_servers=[mcp_server])
        async with agent.run_mcp_servers():
            result = await agent.run("List available trading pairs.")
    """
    if not config.platform_api_key:
        raise ValueError(
            "AgentConfig.platform_api_key is empty. "
            "Set PLATFORM_API_KEY in agent/.env or the environment before creating the MCP server. "
            "The MCP server subprocess requires MCP_API_KEY and will exit with code 1 if it is missing."
        )

    env: dict[str, str] = {
        # Inherit the full parent environment so PATH, virtual-env binaries,
        # PYTHONPATH, and other process-level settings are all available inside
        # the subprocess.
        **os.environ,
        # Required: the API key used for all X-API-Key authenticated REST calls.
        "MCP_API_KEY": config.platform_api_key,
        # Point the MCP server at the correct platform instance.
        "API_BASE_URL": config.platform_base_url,
        # Keep MCP server logging at WARNING to prevent any stderr noise from
        # interfering with the stdio JSON-RPC stream on stdout.
        "LOG_LEVEL": "WARNING",
    }

    # Optionally inject a pre-issued JWT token.  Required for JWT-only endpoints
    # such as /api/v1/agents/* and /api/v1/battles/*.  When not provided, those
    # tools will return 401 errors — which is acceptable if the agent does not
    # need agent-management or battle functionality.
    if config.platform_api_secret:
        # The MCP server reads MCP_JWT_TOKEN from the environment.  However, raw
        # secrets should not be forwarded as JWTs directly.  Instead, callers that
        # need JWT-protected endpoints should obtain a JWT via the SDK login flow
        # and pass it explicitly.  Here we expose the hook so that a pre-issued
        # JWT can be injected at construction time via a subclass or monkey-patch
        # in tests.  By default the secret is NOT forwarded.
        pass  # Intentionally left as a no-op; see docstring above.

    return MCPServerStdio(
        # Use the same Python interpreter that is running this process.  This
        # guarantees the subprocess sees the same virtual environment, installed
        # packages, and sys.path roots.
        command=sys.executable,
        args=["-m", "src.mcp.server"],
        env=env,
        # Start the subprocess from the project root so that `src` is importable.
        cwd=str(config.platform_root),
    )


def get_mcp_server_with_jwt(config: AgentConfig, jwt_token: str) -> MCPServerStdio:
    """Create an MCP server with a pre-issued JWT for JWT-only endpoints.

    Identical to :func:`get_mcp_server` but additionally injects a JWT token as
    ``MCP_JWT_TOKEN``.  Use this variant when the agent needs to call endpoints
    under ``/api/v1/agents/`` or ``/api/v1/battles/`` which require Bearer-token
    authentication.

    The JWT can be obtained ahead of time via the SDK::

        async with AsyncAgentExchangeClient(
            api_key=config.platform_api_key,
            api_secret=config.platform_api_secret,
        ) as client:
            # SDK acquires the JWT automatically on first request.
            await client.get_balance()
            jwt_token = client._jwt_token   # internal attribute — prefer SDK methods

    Or directly via the REST API::

        import httpx
        resp = httpx.post(
            f"{config.platform_base_url}/api/v1/auth/login",
            json={"api_key": config.platform_api_key, "api_secret": config.platform_api_secret},
        )
        jwt_token = resp.json()["token"]

    Args:
        config: Fully-populated :class:`~agent.config.AgentConfig` instance.
        jwt_token: A valid JWT obtained from ``POST /api/v1/auth/login``.  The MCP
            server will forward this as ``Authorization: Bearer <jwt>`` on every
            REST request that supports it.

    Returns:
        A configured :class:`~pydantic_ai.mcp.MCPServerStdio` instance with JWT
        support enabled.

    Raises:
        ValueError: If ``config.platform_api_key`` is empty (see :func:`get_mcp_server`).
        ValueError: If ``jwt_token`` is empty or whitespace-only.

    Example::

        config = AgentConfig()
        jwt = await acquire_jwt(config)  # your helper
        mcp_server = get_mcp_server_with_jwt(config, jwt)

        agent = Agent(model=config.agent_model, mcp_servers=[mcp_server])
        async with agent.run_mcp_servers():
            result = await agent.run("List all agents and start a battle between the top two.")
    """
    if not jwt_token or not jwt_token.strip():
        raise ValueError("jwt_token must be a non-empty string.")

    # Build the base server first (validates platform_api_key).
    base_server = get_mcp_server(config)

    # Overlay MCP_JWT_TOKEN onto the already-merged env dict.
    env_with_jwt: dict[str, str] = {
        **(base_server.env or {}),
        "MCP_JWT_TOKEN": jwt_token,
    }

    return MCPServerStdio(
        command=base_server.command,
        args=list(base_server.args or []),
        env=env_with_jwt,
        cwd=base_server.cwd,
    )
