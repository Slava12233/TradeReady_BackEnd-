---
task_id: 8
title: "System prompt & skill context loader"
type: task
agent: "backend-developer"
phase: 4
depends_on: [7]
status: "completed"
board: "[[tradeready-test-agent/README]]"
priority: "medium"
files:
  - "agent/prompts/system.py"
  - "agent/prompts/skill_context.py"
  - "agent/prompts/__init__.py"
tags:
  - task
  - testing-agent
---

# Task 8: System prompt & skill context loader

## Assigned Agent: `backend-developer`

## Objective
Implement the system prompt that defines the agent's identity and behavior, plus a skill context loader that fetches the platform's `skill.md` for enriched reasoning.

## Files to Create

### `agent/prompts/system.py`
- `SYSTEM_PROMPT: str` constant containing the agent's identity, testing purpose, trading rules, and error handling instructions
- See plan Section 4.1 for the full prompt content

### `agent/prompts/skill_context.py`
- `async def load_skill_context(config: AgentConfig) -> str` — fetches `skill.md` from the platform's REST API for dynamic context injection
- Falls back to empty string if fetch fails
- Uses httpx for the HTTP call

### `agent/prompts/__init__.py`
- Re-export `SYSTEM_PROMPT` and `load_skill_context`

## Acceptance Criteria
- [ ] `SYSTEM_PROMPT` covers: identity, testing purpose, workflow instructions, trading rules, error handling
- [ ] `load_skill_context()` fetches from platform API and handles failures gracefully
- [ ] Prompt is specific enough that different LLMs will follow it consistently
- [ ] No hardcoded credentials in the prompt

## Dependencies
- Task 7 (models) — prompt references the output model types

## Agent Instructions
- Read plan Section 4.1 for the system prompt content
- The skill context endpoint is `GET /api/v1/agents/{agent_id}/skill.md` (requires JWT auth)
- If the agent doesn't have JWT access, fall back to reading `docs/skill.md` from disk
- Keep the prompt under 2000 tokens to leave room for tool descriptions

## Estimated Complexity
Low — mostly string content with one HTTP function
