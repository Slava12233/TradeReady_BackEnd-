"""MCP Server — Model Context Protocol integration for AI agents.

Exposes 12 trading tools over the MCP stdio transport so that Claude-based
agents and any MCP-compatible framework can discover and invoke trading
operations against the platform's REST API.

Modules:
    tools   -- Tool definitions, parameter schemas, and REST-call wiring.
    server  -- MCP server process entry point; registers tools and listens
               on stdio transport.

Usage::

    python -m src.mcp.server
"""
