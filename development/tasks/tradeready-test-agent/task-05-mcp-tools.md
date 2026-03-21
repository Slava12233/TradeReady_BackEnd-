---
task_id: 5
title: "MCP tools module"
type: task
agent: "backend-developer"
phase: 2
depends_on: [2, 3]
status: "completed"
board: "[[tradeready-test-agent/README]]"
priority: "medium"
files:
  - "agent/tools/mcp_tools.py"
tags:
  - task
  - testing-agent
---

# Task 5: MCP tools module

## Assigned Agent: `backend-developer`

## Objective
Implement `agent/tools/mcp_tools.py` — MCP server connection using Pydantic AI's `MCPServerStdio` for auto-discovering all 58 platform tools.

## Context
MCP provides discovery-mode access to ALL platform tools at once. The agent can use this for exploration and for tools not covered by the SDK. Pydantic AI has native MCP client support.

## Files to Create
- `agent/tools/mcp_tools.py` — `get_mcp_server(config: AgentConfig) -> MCPServerStdio` function:
  - Creates `MCPServerStdio` pointing to `python -m src.mcp.server`
  - Passes `MCP_API_KEY` via env vars
  - Sets `cwd` to platform root (parent of `agent/`)
  - Optionally passes `MCP_JWT_TOKEN` if available

## Acceptance Criteria
- [ ] `MCPServerStdio` correctly configured with command, env, and cwd
- [ ] MCP API key passed via environment (not command args)
- [ ] Platform root path resolved correctly relative to agent package
- [ ] Function is importable and returns the server object
- [ ] Usage example in docstring showing how to add to an Agent

## Dependencies
- Task 2 (config) — needs `AgentConfig` for API key and platform root
- Task 3 (research) — needs MCP server connection pattern

## Agent Instructions
- Read `src/mcp/CLAUDE.md` for how the MCP server works
- Read the research output at `development/tasks/tradeready-test-agent/research-integration-surfaces.md`
- Import from `pydantic_ai.mcp import MCPServerStdio`
- The MCP server runs as a subprocess — pass env vars through `env` parameter
- Include `**os.environ` in env dict to inherit PATH and other system vars

## Estimated Complexity
Low — single function, mostly configuration
