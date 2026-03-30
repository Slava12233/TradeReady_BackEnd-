---
type: code-review
date: 2026-03-30
reviewer: code-reviewer
verdict: PASS WITH WARNINGS
scope: deployment-v002
tags:
  - review
  - deployment
  - config
  - battles
  - tasks
  - mcp
  - ci-cd
---

# Code Review Report

- **Date:** 2026-03-30 21:46
- **Reviewer:** code-reviewer agent
- **Verdict:** PASS WITH WARNINGS

## Files Reviewed

**Backend:**
- `src/config.py`
- `src/main.py`
- `src/mcp/tools.py`
- `src/api/routes/battles.py`
- `src/api/routes/agents.py`
- `src/api/routes/training.py`
- `src/api/routes/strategy_tests.py`
- `src/tasks/agent_analytics.py`
- `src/tasks/strategy_tasks.py`
- `src/tasks/battle_snapshots.py`
- `src/dependencies.py`
- `src/exchange/adapter.py`
- `src/exchange/ccxt_adapter.py`
- `src/exchange/symbol_mapper.py`
- `src/database/repositories/strategy_repo.py`
- `src/database/repositories/training_repo.py`
- `src/database/repositories/battle_repo.py`
- `src/battles/presets.py`
- `src/battles/service.py`
- `src/battles/snapshot_engine.py`

**CI/CD:**
- `.github/workflows/test.yml`
- `.github/workflows/deploy.yml`
- `.env.example`

**Tests:**
- `tests/unit/test_mcp_tools.py`
- `tests/unit/test_mcp_strategy_tools.py`
- `tests/unit/test_agent_permissions.py`
- `tests/unit/test_ab_testing.py`

## CLAUDE.md Files Consulted

- `CLAUDE.md` (root — cross-cutting standards)
- `src/tasks/CLAUDE.md`
- `.claude/agent-memory/code-reviewer/MEMORY.md`

## Critical Issues

None.

## Warnings

### W1 — `src/tasks/strategy_tasks.py`: stdlib `logging` instead of `structlog`

- **File:** `src/tasks/strategy_tasks.py:13,18`
- **Rule violated:** Logging convention — all modules must use `structlog.get_logger(__name__)`, never stdlib `logging.getLogger`
- **Issue:** The file uses `import logging` and `logger = logging.getLogger(__name__)`. This is a pre-existing issue that was not fixed in this changeset. `src/tasks/agent_analytics.py` (also changed in this PR) correctly uses `structlog.get_logger(__name__)`, making the inconsistency visible.
- **Fix:** Replace `import logging` / `logger = logging.getLogger(__name__)` with `import structlog` / `logger = structlog.get_logger(__name__)`. Update all `logger.debug(...)` / `logger.exception(...)` calls to use keyword arguments per structlog convention.

### W2 — `src/api/routes/agents.py`: `ResourceNotFoundError` referenced in docstring but does not exist

- **File:** `src/api/routes/agents.py:915`
- **Rule violated:** Documentation accuracy
- **Issue:** The docstring for `update_feedback` still lists `ResourceNotFoundError: If the feedback row does not exist.` in its `Raises:` section. The implementation was correctly changed to raise `HTTPException(404)` (since `ResourceNotFoundError` does not exist in `src/utils/exceptions.py`), but the docstring was not updated.
- **Fix:** Remove `ResourceNotFoundError` from the `Raises:` section of the `update_feedback` docstring, or replace it with a note that a 404 response is returned.

### W3 — `src/api/routes/agents.py`: `HTTPException` instead of custom `TradingPlatformError` subclass

- **File:** `src/api/routes/agents.py:943`
- **Rule violated:** Exception hierarchy — all exceptions should inherit `TradingPlatformError`; error format must be `{"error": {"code": "...", "message": "..."}}`
- **Issue:** `raise HTTPException(status_code=404, detail=f"Feedback {feedback_id} not found for agent {agent_id}.")` produces FastAPI's default error format `{"detail": "..."}`, not the project standard `{"error": {"code": "...", "message": "..."}}`. Every other 404 in the codebase uses a `TradingPlatformError` subclass serialized by the global exception handler.
- **Fix:** Either (a) add `ResourceNotFoundError` to `src/utils/exceptions.py` as a `TradingPlatformError` subclass with `http_status = 404` and use it here, or (b) raise any existing 404-class exception from the hierarchy (e.g. `AgentNotFoundError` if one exists). This keeps the API error format consistent for consumers.

### W4 — `.github/workflows/deploy.yml`: hardcoded `alembic downgrade -3` in rollback

- **File:** `.github/workflows/deploy.yml:66`
- **Rule violated:** Deployment safety
- **Issue:** The rollback path runs `alembic downgrade -3` (three steps back) regardless of how many migrations were applied in this deployment. If this deploy applied 1 migration, rolling back 3 steps reverts data that was already live before the deploy. If it applied 4 migrations, the rollback is insufficient.
- **Fix:** Capture the current migration revision before running `upgrade head` and use a targeted `alembic downgrade <pre-deploy-rev>` in the rollback path. Example:
  ```bash
  ROLLBACK_REV=$(docker compose exec -T api alembic current --verbose | grep '(head)' | awk '{print $1}')
  # ... run upgrade head ...
  # in rollback:
  docker compose exec -T api alembic downgrade "$ROLLBACK_REV"
  ```

### W5 — `src/tasks/strategy_tasks.py`: `float()` conversion of monetary values in episode metrics

- **File:** `src/tasks/strategy_tasks.py:157-163`
- **Rule violated:** Decimal rule — `float` must never be used for monetary values
- **Issue:** `roi_pct`, `total_fees`, `final_equity`, `sharpe_ratio`, `max_drawdown_pct`, and `win_rate` are all cast with `float()` when building the metrics dict. `total_fees` and `final_equity` are monetary values (Decimal). `roi_pct`, `sharpe_ratio`, `max_drawdown_pct`, `win_rate` are financial ratios where precision matters for downstream analysis and comparison. This was pre-existing code, but the changeset added a `# type: ignore[arg-type]` comment to `sharpe_ratio` conversion without fixing the underlying float conversion.
- **Fix:** Store monetary values as `str(result.total_fees)` and `str(result.final_equity)` in the dict (the callers that persist these to DB can parse them as `Decimal`). For ratio/percentage values (`roi_pct`, `sharpe_ratio`, etc.), `str(...)` is also acceptable. The downstream DB write in `repo.save_episode()` should be checked to ensure it handles string conversion correctly.

### W6 — `src/tasks/strategy_tasks.py:180`: `except Exception` without `# noqa: BLE001`

- **File:** `src/tasks/strategy_tasks.py:180`
- **Rule violated:** Exception handling — `except Exception` is only valid for LLM/pydantic-ai varied exception surfaces; must be suppressed with `# noqa: BLE001`
- **Issue:** The bare `except Exception:` at line 180 wraps the entire episode execution. This is a Celery task catch-all for isolation purposes (a known valid use case), but it is missing the `# noqa: BLE001` suppression comment that the project uses to signal intentional broad catches.
- **Fix:** Add `# noqa: BLE001` with a brief comment explaining the intent: `except Exception:  # noqa: BLE001 — task-level isolation; log and mark episode failed`.

## Suggestions

### S1 — `src/main.py`: lazy import of `get_settings` inside `create_app`

- **File:** `src/main.py:169`
- **Issue:** `from src.config import get_settings  # noqa: PLC0415` is placed inside `create_app()` with a `PLC0415` suppression. The `# noqa: PLC0415` suppression is intended only for circular import avoidance. `src/config.py` has no circular import risk with `src/main.py` — `main.py` is a top-level module that does not get re-imported by `config.py`. The suppression is technically misused here.
- **Suggestion:** Move `from src.config import get_settings` to the module-level imports at the top of `src/main.py`, eliminating the need for the `# noqa` suppression. This also makes the dependency explicit.

### S2 — `.github/workflows/deploy.yml`: missing `--no-input` flag on `alembic upgrade`

- **File:** `.github/workflows/deploy.yml:44`
- **Issue:** `alembic upgrade head` in CI will block on interactive prompts if a migration file ever has an interactive element (unlikely but possible with custom migration scripts). In automated pipelines this is best protected explicitly.
- **Suggestion:** Add environment variable `PYTHONUNBUFFERED=1` or pass a timeout to the `docker compose exec -T` call. The `-T` flag already disables pseudo-TTY, which should be sufficient — this is a minor hardening note.

### S3 — `src/mcp/tools.py`: `body` variable shadowed after `create_strategy` case

- **File:** `src/mcp/tools.py:1740`
- **Issue:** In the `create_strategy_version` case (line ~1740), the variable `body` is reused with `body = {"definition": ...}`. Earlier in the same `_dispatch` function, `body` was used as the local variable in `create_strategy` before being renamed to `strategy_body`. Now `body` is a different dict in `create_strategy_version`. This is not a bug, but inconsistent naming makes the function harder to audit.
- **Suggestion:** Rename the `create_strategy_version` local dict to `version_body` to match the rename pattern applied in `create_strategy`.

### S4 — `tests/unit/test_mcp_strategy_tools.py`: `@pytest.mark.asyncio` decorator still present

- **File:** `tests/unit/test_mcp_strategy_tools.py:450`
- **Issue:** The test at line 450 has `@pytest.mark.asyncio` applied. The project uses `asyncio_mode = "auto"` in `pyproject.toml`, making this decorator redundant (not harmful, but inconsistent with the pattern in the rest of the test suite).
- **Suggestion:** Remove the `@pytest.mark.asyncio` decorator to match the `asyncio_mode = "auto"` convention.

## Passed Checks

- **Decimal rule (monetary values):** `src/battles/service.py`, `src/battles/snapshot_engine.py`, `src/tasks/agent_analytics.py`, `src/database/repositories/*` all correctly use `Decimal` for PnL, balances, and equity. The `coverage_pct` in `agent_analytics.py` is a percentage stored as float, which is acceptable.
- **`BattleInvalidStateError` import moved correctly:** All four lazy imports now pull from `src.utils.exceptions` (where the class is defined at line 920) instead of `src.battles.service`. This is a correct fix — the previous import from `service` was importing from the wrong layer.
- **Dependency direction:** No violations observed. `src/battles/routes.py` → `src/battles/service.py` → `src/battles/snapshot_engine.py` chain is intact. Repository files do not import from routes or services.
- **Type-ignore specificity:** The new `# type: ignore[attr-defined]`, `# type: ignore[arg-type]`, `# type: ignore[misc]`, `# type: ignore[no-any-return]`, `# type: ignore[return-value]` comments all include specific error codes rather than bare `# type: ignore`. This is correct per project standards.
- **Stale `# type: ignore` removal:** Removing stale `# type: ignore[type-arg]` on `RedisDep` and `CircuitBreakerRedisDep` type aliases in `src/dependencies.py` is correct — these were suppressions for a type annotation issue that was resolved.
- **Stale `# type: ignore[assignment]` removal:** Removals in `strategy_repo.py`, `training_repo.py`, and `battle_repo.py` are correct — mypy now resolves these assignments without needing suppression.
- **`cors_origins` field:** The new `cors_origins: str` field in `src/config.py` follows Pydantic v2 `BaseSettings` conventions. The comma-split in `src/main.py` is correct. The `.env.example` entry is present. No secrets are hardcoded — defaults are localhost-only.
- **`strategy_body` rename:** The `body → strategy_body` rename in `_dispatch` for the `create_strategy` case avoids shadowing with the later `body` dict in `create_strategy_version`. This is a valid improvement.
- **Test: `test_ab_testing.py` Decimal fix:** The `pnls_a`/`pnls_b` lists now use `Decimal` values, which correctly matches the `_run_significance_test` function signature. This fixes the float violation in the test.
- **Test: `test_mcp_tools.py` tool count update 43→58:** The count update is consistent — `TOOL_COUNT`, `test_tool_count_constant_matches`, `test_forty_three_tools_defined` (now "58"), and `TestRegisterTools.test_register_tools` all updated to 58. The `EXPECTED_TOOL_NAMES` set has 58 entries covering all 7 new strategy/training tools.
- **Test: `test_mcp_strategy_tools.py` UUID run IDs:** Replacing `"run-1"` / `"run-2"` with valid UUID strings for `compare_training_runs` is correct — the `_dispatch` handler validates each run_id as a UUID, so the old test would have returned an error response.
- **Test: `test_agent_permissions.py` ADMIN role mock:** Adding `patch.object(self.manager, "get_role", return_value=AgentRole.ADMIN)` correctly satisfies the role-check guard in `grant_capability` and `revoke_capability`. The added `revoker_id` parameter in `revoke_capability` test is consistent with the actual function signature.
- **CI/CD — `test.yml` branch triggers:** Adding `workflow_call` trigger is correct — the `deploy.yml` uses `uses: ./.github/workflows/test.yml` (reusable workflow call), which requires the `workflow_call` trigger to be defined. Without it, the deploy workflow would fail.
- **CI/CD — deploy workflow backup/rollback:** The pre-deploy `pg_dump` backup and `git rev-parse HEAD` rollback point are sound additions. The health check with automatic rollback is a substantial improvement over the previous deploy pipeline.
- **Naming conventions:** All new variables, files, and constants follow `snake_case` / `UPPER_SNAKE_CASE` conventions.
- **Import order:** All changed files maintain stdlib → third-party → local ordering. Lazy imports inside functions correctly use `# noqa: PLC0415`.
- **No bare `except:`:** No unqualified `except:` clauses introduced.
- **No hardcoded secrets:** `cors_origins` defaults are localhost URLs only (no production credentials embedded).
- **API prefix:** No new routes added; existing routes remain under `/api/v1/`.
- **`dict` type annotation fix in `presets.py`:** Changing `config = {` to `config: dict[str, object] = {` provides an explicit type annotation, consistent with mypy strict mode requirements.
