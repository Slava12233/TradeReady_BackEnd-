---
type: code-review
date: 2026-03-20
reviewer: code-reviewer
verdict: PASS WITH WARNINGS
scope: agent-package
tags:
  - review
  - agent
  - workflows
---

# Code Review Report

- **Date:** 2026-03-20 11:29
- **Reviewer:** code-reviewer agent
- **Verdict:** PASS WITH WARNINGS

## Files Reviewed

- `agent/__init__.py`
- `agent/__main__.py`
- `agent/config.py`
- `agent/main.py`
- `agent/models/__init__.py`
- `agent/models/analysis.py`
- `agent/models/report.py`
- `agent/models/trade_signal.py`
- `agent/prompts/__init__.py`
- `agent/prompts/skill_context.py`
- `agent/prompts/system.py`
- `agent/tools/__init__.py`
- `agent/tools/mcp_tools.py`
- `agent/tools/rest_tools.py`
- `agent/tools/sdk_tools.py`
- `agent/workflows/__init__.py`
- `agent/workflows/smoke_test.py`
- `agent/workflows/trading_workflow.py`
- `agent/workflows/backtest_workflow.py`
- `agent/workflows/strategy_workflow.py`
- `agent/tests/__init__.py`
- `agent/tests/test_config.py`
- `agent/tests/test_models.py`
- `agent/tests/test_rest_tools.py`
- `agent/tests/test_sdk_tools.py`
- `agent/pyproject.toml`
- `agent/.env.example`

## CLAUDE.md Files Consulted

- `CLAUDE.md` (root — cross-cutting standards)
- `development/context.md` (current project state)

---

## Critical Issues

None.

---

## Warnings

### W1 — `backtest_workflow.py`: Private method `_get` called directly on the `PlatformRESTClient`

- **File:** `agent/workflows/backtest_workflow.py:207` and `:247`
- **Rule violated:** Architecture / encapsulation — callers should use the public API, not internal helpers
- **Issue:** Both the health-check step and the data-range discovery step call `client._get(...)` directly instead of going through a named public method on `PlatformRESTClient`. This couples the workflow tightly to the internal implementation of the client, and makes it fragile if `_get` is ever renamed or its signature changes.
  ```python
  health_response = await client._get("/api/v1/health")
  data_range = await client._get("/api/v1/market/data-range")
  ```
- **Fix:** Add two public methods to `PlatformRESTClient`:
  ```python
  async def health_check(self) -> dict[str, Any]:
      return await self._get("/api/v1/health")

  async def get_data_range(self) -> dict[str, Any]:
      return await self._get("/api/v1/market/data-range")
  ```
  Then update the workflow to call `client.health_check()` and `client.get_data_range()`.

---

### W2 — `strategy_workflow.py`: Overly broad `except Exception` used in multiple places without re-narrowing

- **File:** `agent/workflows/strategy_workflow.py:283`, `:337`, `:495`, `:552`, `:638`
- **Rule violated:** Error handling standard — bare `except Exception` is used five times. Each is annotated `# noqa: BLE001`, which correctly suppresses the linter warning, but the strategy workflow uses these catches on library calls (`client.create_strategy`, `client.test_strategy`, `client.create_version`, `client.compare_versions`) that only surface `httpx.HTTPStatusError` or `httpx.RequestError` in practice. The broad catch is also used in the LLM review step (step 4) where it is appropriate.
- **Issue:** For the pure HTTP calls (steps 1, 2, 6, 7, 9), catching `Exception` will swallow `KeyboardInterrupt` subclasses and `asyncio.CancelledError` (which inherits from `BaseException` in Python 3.8+ but from `Exception` in earlier versions). More importantly it hides unexpected programming errors (e.g., `AttributeError`, `TypeError`) by routing them into `bugs_found` instead of raising, making debugging harder.
- **Fix:** Narrow the catches on HTTP calls to `(httpx.HTTPStatusError, httpx.RequestError)` as is done correctly in `backtest_workflow.py`. Keep `except Exception` only for the LLM step (step 4) and polling helper, where pydantic-ai can raise varied exception types.

---

### W3 — `backtest_workflow.py`: `_sma` and `_extract_closes` use `float` for financial data

- **File:** `agent/workflows/backtest_workflow.py:62–127`
- **Rule violated:** `Decimal` for ALL monetary values — never `float`
- **Issue:** The moving-average signal functions operate on `float` lists extracted from candle close prices. These functions are internal decision heuristics (not stored in the DB or sent to the platform), but they're computing signals based on financial prices. While a testing/signal-computation context is less strict than balance/order arithmetic, `float` arithmetic on prices can produce silently wrong crossover signals due to rounding.
  ```python
  def _sma(closes: list[float], window: int) -> float | None: ...
  def _extract_closes(...) -> list[float]: ...
  ```
  The docstring of `_extract_closes` even notes that values come from `get_backtest_candles` which itself returns string-serialised decimals.
- **Fix:** Since these are signal heuristics and the platform standard notes that `Decimal` is required for monetary values, use `Decimal` here for full consistency:
  ```python
  from decimal import Decimal
  def _sma(closes: list[Decimal], window: int) -> Decimal | None:
      if len(closes) < window:
          return None
      return sum(closes[-window:]) / window
  ```
  Alternatively, document clearly with a comment that `float` is intentional here for heuristic-only signal purposes (not monetary accounting). The current code has no such comment.

---

### W4 — `strategy_workflow.py`: LLM agent uses deprecated `result_type` instead of `output_type`

- **File:** `agent/workflows/strategy_workflow.py:438–446`
- **Rule violated:** Pydantic AI patterns — `output_type` is the current API (used correctly everywhere else in the codebase); `result_type` is the old v1 API
- **Issue:**
  ```python
  review_agent: Agent[None, str] = Agent(
      model=config.agent_cheap_model,
      result_type=str,          # <-- deprecated kwarg
      system_prompt=...
  )
  review_result = await review_agent.run(review_prompt)
  llm_improvement_notes = review_result.data   # <-- deprecated attribute
  ```
  All other agent instantiations in the package use `output_type=` and access `result.output`. Using `result_type` and `.data` works in older pydantic-ai versions but is the v1 API and will be removed in future releases. This is an inconsistency that will silently break on a version upgrade.
- **Fix:**
  ```python
  review_agent: Agent[None, str] = Agent(
      model=config.agent_cheap_model,
      output_type=str,
      system_prompt=...
  )
  review_result = await review_agent.run(review_prompt)
  llm_improvement_notes = review_result.output
  ```

---

### W5 — `trading_workflow.py:508`: Unevaluated f-string literal in evaluation prompt

- **File:** `agent/workflows/trading_workflow.py:508`
- **Rule violated:** Code correctness — the f-string template contains a curly-brace expression that will not be evaluated
- **Issue:** Inside an f-string, `{signal.symbol}` appears as a literal brace group `{signal.symbol}` — but this particular occurrence is inside a regular string (not an f-string) that is concatenated to the f-string above it:
  ```python
  evaluation_prompt = (
      f"You have just completed a live trading workflow for {signal.symbol}.  "
      ...
      "Analyse the {signal.symbol} market conditions at the time of this trade "  # BUG
  ```
  The last line is a plain `str` literal (no `f` prefix), so `{signal.symbol}` is passed literally to the LLM as the string `"Analyse the {signal.symbol} market conditions"` rather than the actual symbol value (e.g., `"Analyse the BTCUSDT market conditions"`). The LLM receives a templating artifact in its prompt.
- **Fix:** Add the `f` prefix:
  ```python
  f"Analyse the {signal.symbol} market conditions at the time of this trade "
  ```

---

### W6 — `models/analysis.py`: `indicators` field uses unparameterised `dict` type

- **File:** `agent/models/analysis.py:56`
- **Rule violated:** Type safety — `dict` without parameters loses type information and triggers mypy warnings in strict mode
- **Issue:**
  ```python
  indicators: dict = Field(default_factory=dict, ...)
  ```
  The `WorkflowResult.metrics` field has the same pattern. Mypy strict mode will flag bare `dict` as `Dict[Unknown, Unknown]`.
- **Fix:** Use a typed mapping or explicit `Any`:
  ```python
  from typing import Any
  indicators: dict[str, Any] = Field(default_factory=dict, ...)
  metrics: dict[str, Any] = Field(default_factory=dict, ...)
  ```

---

### W7 — `tools/rest_tools.py`: Logger uses stdlib `logging` while rest of package uses `structlog`

- **File:** `agent/tools/rest_tools.py:20`
- **Rule violated:** Consistency — the rest of the `agent/` package uniformly uses `structlog`. `rest_tools.py` is the only file that uses `logging.getLogger`.
- **Issue:**
  ```python
  import logging
  logger = logging.getLogger(__name__)
  ```
  All other files (`sdk_tools.py`, `smoke_test.py`, `trading_workflow.py`, `backtest_workflow.py`, `strategy_workflow.py`, `skill_context.py`) use `structlog.get_logger(__name__)`. This means REST client errors are emitted in a different format, uncorrelated with the structured JSON context added by `structlog.configure()` in `main.py`.
- **Fix:**
  ```python
  import structlog
  logger = structlog.get_logger(__name__)
  ```
  Replace `logger.error(...)` and `logger.error(...)` calls with the structlog event/key-value style consistently used elsewhere.

---

### W8 — `tests/test_models.py`: Frozen-model immutability tests use overly broad `pytest.raises(Exception)`

- **File:** `agent/tests/test_models.py:143`, `:201`, `:317`, `:397`, `:499`
- **Rule violated:** Test quality — catching `Exception` instead of the specific Pydantic `ValidationError` (for frozen models, Pydantic raises `ValidationError` or `PydanticUserError` depending on version)
- **Issue:**
  ```python
  with pytest.raises(Exception):
      sig.symbol = "ETHUSDT"
  ```
  Using `Exception` means the test would pass even if a completely unrelated error occurred. The specific exception for frozen-model mutation in Pydantic v2 is `pydantic_core.core_schema.ValidationError` or `pydantic.PydanticUserError`. This is a test quality issue, not a blocking defect.
- **Fix:**
  ```python
  from pydantic import ValidationError
  with pytest.raises((ValidationError, TypeError)):
      sig.symbol = "ETHUSDT"
  ```
  (Pydantic v2 raises `ValidationError` for frozen model assignments in some contexts and `TypeError`/`pydantic.PydanticUserError` in others depending on how the assignment occurs.)

---

## Suggestions

### S1 — `config.py`: `platform_api_key` defaults to empty string — consider `SecretStr`

`platform_api_key` and `platform_api_secret` are stored as plain `str`. Pydantic v2 offers `SecretStr` which prevents the values from appearing in `repr()`, `model_dump()`, and logs by default. Since the system prompt explicitly warns against logging API keys, using `SecretStr` provides an automatic safety net. The fields would need `.get_secret_value()` calls at use sites, but that trade-off is worthwhile for secrets.

### S2 — `smoke_test.py`: Step 5 silently credits success when step 4 failed

In `smoke_test.py` lines 233–234, when the buy order from step 4 failed, step 5 (position check) increments `steps_completed += 1` with the comment "credit step as structurally valid." This inflates the completion count. The reported `steps_completed` will exceed the actual number of meaningful steps validated, which can shift the outcome from `"fail"` to `"partial"` incorrectly. Consider not incrementing `steps_completed` for skipped steps, or tracking skipped vs. completed separately.

### S3 — `mcp_tools.py`: The `platform_api_secret` block is a no-op with a misleading comment

Lines 112–119 in `mcp_tools.py` contain a conditional `if config.platform_api_secret: pass` block with a long comment explaining that secrets "should not be forwarded as JWTs directly." The comment is accurate, but the code block adds no functionality — it only adds confusion. Either remove the block entirely or replace it with a `logger.debug(...)` noting that the secret is intentionally not forwarded to make the intent explicit without dead code.

### S4 — `backtest_workflow.py`: `steps_total` is a magic number with no constant

`steps_total = 7` is hardcoded inline at line 197 without a named constant. All other workflow files either use a named constant (`_TOTAL_STEPS = 9` in `trading_workflow.py`) or a named variable with a comment. Adding `_STEPS_TOTAL = 7` (like `smoke_test.py` does with `_STEPS_TOTAL = 10`) would make it consistent and easier to maintain when steps are added.

### S5 — `strategy_workflow.py`: `_build_v2_definition` imports `copy` lazily without `noqa`

Line 158: `import copy` inside a function body. Per project convention, lazy imports inside functions require `# noqa: PLC0415` when they exist to avoid circular imports. Here there is no circular import risk — `copy` is a stdlib module. Move it to the module top-level imports to be consistent with the project's import ordering convention (stdlib → third-party → local).

### S6 — Missing tests for workflow files

The `agent/tests/` directory contains tests for `config.py`, `models/`, `tools/rest_tools.py`, and `tools/sdk_tools.py`, but has no tests for any of the four workflow files (`smoke_test.py`, `trading_workflow.py`, `backtest_workflow.py`, `strategy_workflow.py`). These are the most complex files in the package. At minimum, unit tests for the pure helper functions (`_sma`, `_ma_signal`, `_extract_closes`, `_safe_float`, `_build_v2_definition`, `_extract_metrics`, `_derive_platform_health`, `_build_summary`, `_any_failure`) would significantly improve coverage and catch regressions like W5 (the missing f-string prefix) automatically.

### S7 — `pyproject.toml`: `mypy` is not in the dev dependencies

The project root enforces `mypy src/` as a mandatory pre-merge check. The `agent/` package's `pyproject.toml` includes `ruff` in dev dependencies but omits `mypy`. This means a developer installing only the agent's dev extras will not have `mypy` available for type-checking the agent package, which is especially relevant given W6 (unparameterised `dict` types).

---

## Passed Checks

- **Security — No hardcoded secrets:** All API keys, secrets, and JWT tokens are loaded exclusively from environment variables via `AgentConfig` / `pydantic-settings`. No secrets appear in source code. The system prompt explicitly instructs the LLM not to log API keys. The `.env.example` correctly uses placeholder values only.
- **Security — API key not logged in REST client:** `rest_tools.py` logs the path and status on HTTP errors but never logs the `X-API-Key` header value. `sdk_tools.py` logs warnings with error messages only, not credentials.
- **Security — MCP subprocess env handling:** `mcp_tools.py` correctly overlays `MCP_API_KEY` on `os.environ` (inheriting PATH and virtualenv), and the `platform_api_secret` is explicitly NOT forwarded to the subprocess as a raw secret.
- **Async correctness:** All I/O operations use `async/await`. No blocking calls detected. `asyncio.sleep()` is used for polling delays. SDK client lifecycle is properly managed with `try/finally: await client.aclose()` in smoke test and trading workflow, and `async with` in backtest and strategy workflows.
- **Pydantic v2 patterns:** All models use `BaseModel` (not v1), `ConfigDict(frozen=True)`, `Field(...)` with descriptions, and `@computed_field` with the correct `@property` decorator. `model_dump()`, `model_dump_json()`, `model_validate()`, and `model_copy()` are all used correctly (v2 API).
- **Naming conventions:** All files use `snake_case.py`, all classes use `PascalCase`, all functions use `snake_case`, all module-level constants use `UPPER_SNAKE_CASE`, and all private helpers use `_prefix`. Fully compliant.
- **Google-style docstrings:** Every public class and function has a Google-style docstring with `Args:`, `Returns:`, and `Example::` sections where applicable. Quality is high throughout.
- **Import order:** stdlib → third-party → local, with `from __future__ import annotations` consistently at the top of files that need it. Lazy imports inside functions are annotated with `# noqa: PLC0415`.
- **Error handling — SDK tools:** All `get_sdk_tools` tool functions correctly catch `AgentExchangeError` and return `{"error": str(exc)}` rather than raising, matching the contract described in the system prompt.
- **Error handling — REST tools:** All `get_rest_tools` tool functions correctly catch `(httpx.HTTPStatusError, httpx.RequestError)` and return `{"error": str(exc)}`.
- **`__all__` exports:** All `__init__.py` files define `__all__` lists that match the exported symbols.
- **`asyncio_mode = "auto"`:** Correctly set in `pyproject.toml`. No `@pytest.mark.asyncio` decorators needed or present.
- **Test isolation:** All tests use `monkeypatch` to set environment variables in isolation and pass `_env_file=None` to prevent `AgentConfig` from reading a real `.env` file during tests.
- **`pydantic-settings` configuration:** `SettingsConfigDict` has `extra="ignore"` (unknown env vars are silently dropped), `case_sensitive=False` (lowercase env vars work), and `env_file_encoding="utf-8"`. All correct.
- **MCP server safety:** `get_mcp_server` validates that `platform_api_key` is non-empty before constructing the subprocess, raising `ValueError` with a clear message. The subprocess receives `LOG_LEVEL=WARNING` to prevent stderr noise from corrupting the MCP JSON-RPC stream.
- **Computed field in config:** `platform_root` is a `@computed_field @property` with the correct `# type: ignore[prop-decorator]` suppression. Returns an absolute path and is covered by tests.
- **`WorkflowResult` validation:** `status` field uses a Pydantic regex pattern `r"^(pass|fail|partial)$"` to enforce the contract. `platform_health` uses `r"^(healthy|degraded|broken)$"`. Both are tested in `test_models.py`.
- **Workflow resilience:** All four workflows are designed to never raise an unhandled exception to the caller. All failure paths return a valid `WorkflowResult`. The `main.py` only catches `(ConnectionError, OSError)` and `KeyboardInterrupt` at the top level, which is appropriate.
- **`steps_completed` accounting:** The accounting is deliberate and consistent — each step increments on success, failed steps don't increment, the final step (result compilation) is always incremented.
