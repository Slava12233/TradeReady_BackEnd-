---
task_id: 1
title: "Project scaffolding & pyproject.toml"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "completed"
board: "[[tradeready-test-agent/README]]"
priority: "high"
files:
  - "agent/__init__.py"
  - "agent/pyproject.toml"
  - "agent/.env.example"
  - "agent/models/__init__.py"
  - "agent/tools/__init__.py"
  - "agent/prompts/__init__.py"
  - "agent/workflows/__init__.py"
  - "agent/reports/.gitkeep"
tags:
  - task
  - testing-agent
---

# Task 1: Project scaffolding & pyproject.toml

## Assigned Agent: `backend-developer`

## Objective
Create the `agent/` top-level directory with the full package structure, `pyproject.toml`, and `.env.example`.

## Context
This is the foundation for the TradeReady Platform Testing Agent — a new top-level package alongside `src/`, `sdk/`, and `Frontend/`. It uses Pydantic AI with OpenRouter for LLM access and connects to our platform via SDK, MCP, and REST.

## Files to Create
- `agent/__init__.py` — package root with `__version__ = "0.1.0"`
- `agent/pyproject.toml` — project metadata and dependencies:
  ```
  pydantic-ai-slim[openrouter]>=0.2
  agentexchange (our SDK, pip install -e ../sdk/)
  httpx>=0.28
  python-dotenv>=1.0
  structlog>=24.0
  pydantic-settings>=2.0
  ```
  Dev deps: `pytest>=8.0, pytest-asyncio>=0.24, ruff>=0.8`
- `agent/.env.example` — template with:
  ```
  OPENROUTER_API_KEY=sk-or-v1-...
  PLATFORM_BASE_URL=http://localhost:8000
  PLATFORM_API_KEY=ak_live_...
  PLATFORM_API_SECRET=sk_live_...
  AGENT_MODEL=openrouter:anthropic/claude-sonnet-4-5
  AGENT_CHEAP_MODEL=openrouter:google/gemini-2.0-flash-001
  ```
- `agent/models/__init__.py` — empty init
- `agent/tools/__init__.py` — empty init
- `agent/prompts/__init__.py` — empty init
- `agent/workflows/__init__.py` — empty init
- `agent/reports/.gitkeep` — placeholder for generated reports

## Acceptance Criteria
- [ ] `agent/` directory exists at project root
- [ ] `pyproject.toml` has all required dependencies listed
- [ ] `.env.example` has all required environment variables
- [ ] All subdirectories have `__init__.py` files
- [ ] Package is installable with `pip install -e ".[dev]"`
- [ ] `reports/` directory has `.gitkeep` and is ready to be gitignored

## Dependencies
None — this is the first task.

## Agent Instructions
- Look at `sdk/pyproject.toml` for an example of how this project structures its packages
- Use `requires-python = ">=3.12"` to match the main project
- The `agentexchange` SDK dependency should reference `../sdk/` for local development
- Add `reports/` to the project's `.gitignore`

## Estimated Complexity
Low — file creation only, no logic
