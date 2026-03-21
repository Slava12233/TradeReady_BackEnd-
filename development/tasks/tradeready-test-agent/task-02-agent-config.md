---
task_id: 2
title: "AgentConfig settings class"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1]
status: "completed"
board: "[[tradeready-test-agent/README]]"
priority: "high"
files:
  - "agent/config.py"
tags:
  - task
  - testing-agent
---

# Task 2: AgentConfig settings class

## Assigned Agent: `backend-developer`

## Objective
Implement the `AgentConfig` class using `pydantic-settings` `BaseSettings` for environment-based configuration.

## Context
The agent needs configuration for OpenRouter API access, platform credentials, model selection, and trading behavior limits. This follows the same pattern as `src/config.py` in the main platform.

## Files to Create
- `agent/config.py` — `AgentConfig(BaseSettings)` with fields:
  - `openrouter_api_key: str` — OpenRouter API key
  - `agent_model: str = "openrouter:anthropic/claude-sonnet-4-5"` — primary model
  - `agent_cheap_model: str = "openrouter:google/gemini-2.0-flash-001"` — budget model
  - `platform_base_url: str = "http://localhost:8000"` — platform URL
  - `platform_api_key: str = ""` — platform API key
  - `platform_api_secret: str = ""` — platform API secret
  - `max_trade_pct: float = 0.05` — max 5% equity per trade
  - `symbols: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]` — default symbols
  - `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")`

## Acceptance Criteria
- [ ] `AgentConfig` loads from `.env` file
- [ ] All fields have sensible defaults except `openrouter_api_key`
- [ ] Class is importable: `from agent.config import AgentConfig`
- [ ] Type hints on all fields

## Dependencies
- Task 1 (project structure must exist)

## Agent Instructions
- Reference `src/config.py` for the pattern used in this project
- Use `pydantic_settings.BaseSettings` (not `pydantic.BaseSettings`)
- Add a `platform_root` computed field that resolves to the project root (parent of `agent/`)

## Estimated Complexity
Low — single file, straightforward settings class
