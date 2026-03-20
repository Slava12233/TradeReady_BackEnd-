# agent/prompts — System Prompt and Skill Context

<!-- last-updated: 2026-03-20 -->

> System prompt constant and skill context loader used to initialise all Pydantic AI agents in the testing workflows.

## What This Module Does

Provides the two prompt-related pieces that every workflow agent needs: a static `SYSTEM_PROMPT` string that describes the agent's identity, integration methods, trading rules, and output models; and an async `load_skill_context()` function that fetches the platform's `docs/skill.md` document for use as supplemental context. Together they give LLM agents enough information to operate the platform correctly without exceeding a practical context budget.

## Key Files

| File | Purpose |
|------|---------|
| `system.py` | `SYSTEM_PROMPT` string constant — shared by all workflow agents |
| `skill_context.py` | `load_skill_context(config)` — disk-first then REST fallback for `skill.md` |
| `__init__.py` | Re-exports `SYSTEM_PROMPT` and `load_skill_context` |

## Public API / Key Classes

### `SYSTEM_PROMPT` (`system.py`)

A plain string constant (~2,000 characters). Passed as `system_prompt=SYSTEM_PROMPT` to all Pydantic AI `Agent` constructors in `trading_workflow.py` and `backtest_workflow.py`. The strategy workflow's cheap-model review agent uses its own shorter inline prompt instead.

The prompt covers seven sections:

| Section | Summary |
|---------|---------|
| **Purpose** | Identifies the agent as a systematic tester, not a trading advisor |
| **Integration Methods** | Lists the 7 SDK tools, the 58 MCP tools, and the 11 REST tools by name |
| **Workflow Instructions** | Step-by-step rules for live trading and backtesting sequences |
| **Trading Rules** | 5% max per trade, minimal test quantities, always close positions before workflow ends |
| **Error Handling** | Return `{"error": "..."}` → log and continue; max 3 retries; critical setup failures → mark workflow as partial/fail |
| **Structured Output Models** | Descriptions of all 5 output models: `TradeSignal`, `MarketAnalysis`, `BacktestAnalysis`, `WorkflowResult`, `PlatformValidationReport` |
| **Important Constraints** | Never log secrets, never place real-money trades, treat 5xx as bugs, treat 4xx with known codes as findings |

### `load_skill_context(config: AgentConfig) -> str` (`skill_context.py`)

Async function. Attempts two sources in order and returns the first one that succeeds. Never raises.

| Priority | Source | Mechanism |
|----------|--------|-----------|
| 1 | Local disk | Reads `config.platform_root / "docs" / "skill.md"` via `Path.read_text()` |
| 2 | Remote REST | `GET {config.platform_base_url}/api/v1/docs/skill` via `httpx.AsyncClient` (10 s timeout) |

Returns an empty string (`""`) if both sources fail. The typical usage pattern is:

```python
skill_text = await load_skill_context(config)
full_prompt = SYSTEM_PROMPT + ("\n\n" + skill_text if skill_text else "")
```

The REST fallback handles both `application/json` responses (extracts `payload["content"]`) and plain-text `text/plain` responses (returns `response.text` directly).

## Patterns

- `SYSTEM_PROMPT` is imported at module level in the workflow files — it does not change at runtime.
- `load_skill_context` uses a lazy import for `httpx` inside the fallback branch (`# noqa: PLC0415`) so the import cost is only paid when the disk source fails.
- Both sources failing is not an error — the agent can still operate without skill context. The function logs a `WARNING` via structlog in that case.
- The prompt is intentionally kept under approximately 2,000 tokens so it does not dominate the context window on cheap models like Gemini Flash.

## Gotchas

- `load_skill_context` relies on `config.platform_root` to locate the file. If `platform_root` is wrong (e.g. in tests where `_env_file=None`), the disk read will fail and the function will fall through to the REST fallback.
- The REST fallback issues an unauthenticated `GET` — no `X-API-Key` header is included. This is intentional because `docs/skill.md` is a public documentation endpoint.
- `SYSTEM_PROMPT` is not the full prompt for every agent. The strategy workflow's cheap-model review agent uses a different inline `system_prompt` string rather than importing `SYSTEM_PROMPT`.
- Both `SYSTEM_PROMPT` and `load_skill_context` are used in the trading and backtest workflows. Smoke test and strategy workflow do not call `load_skill_context`.

## Recent Changes

- `2026-03-20` — Initial CLAUDE.md created.
