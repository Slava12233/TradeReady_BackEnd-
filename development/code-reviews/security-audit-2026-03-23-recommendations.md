---
type: code-review
date: 2026-03-23
reviewer: security-auditor
verdict: CONDITIONAL PASS — 1 HIGH finding remains open; 6 of 7 fixes fully verified
scope: "R2-01 through R2-08: all HIGH security fixes from C-level recommendations round 2"
tags:
  - security
  - audit
  - permissions
  - budget
  - redis
  - deserialization
  - cli
---

## Security Audit Report

**Scope:** Tasks R2-01 through R2-08 — all 7 HIGH security issue fixes from the C-level recommendations phase
**Date:** 2026-03-23
**CLAUDE.md files consulted:** `CLAUDE.md` (root), `agent/CLAUDE.md`, `agent/permissions/CLAUDE.md`, `agent/strategies/CLAUDE.md`, `agent/strategies/regime/CLAUDE.md`, `src/database/CLAUDE.md`, `src/database/repositories/CLAUDE.md`, `alembic/CLAUDE.md`

---

### Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH     | 1 |
| MEDIUM   | 1 |
| LOW      | 2 |

---

### Findings

#### [HIGH] R2-04 Incomplete: enforcement.py Does Not Write to agent_audit_log — Still Routes to agent_feedback

- **File:** `agent/permissions/enforcement.py:357–462`
- **Category:** Fix Incomplete / Audit Trail Gap
- **Description:** The R2-04 fix created the `AgentAuditLog` ORM model (`src/database/models.py:3299`), the migration (`alembic/versions/020_add_agent_audit_log.py`), and the repository (`src/database/repositories/agent_audit_log_repo.py`). However, `PermissionEnforcer._persist_audit_entries()` still imports and writes to `AgentFeedbackRepository` and `AgentFeedback`. The `AgentAuditLogRepository` is never referenced in `enforcement.py`. The `audit_allow_events=True` constructor parameter is wired but the allow-event path still executes a `continue` (line 439) — no "allow" events are persisted anywhere.
- **Impact:** The stated goal of R2-04 was to persist both "allow" and "deny" permission check outcomes to a durable, purpose-built audit table. That goal is not achieved:
  1. "Deny" events are written to `agent_feedback` (a human-operator feedback queue, not an audit log) with `category="bug"`, mixing security audit data into bug tracking.
  2. "Allow" events are never persisted, despite the `audit_allow_events=True` flag being passed and documented. Post-restart, the only durable trail is of denied trades — a complete record of authorized trades is still absent.
  3. The `agent_audit_log` table and `AgentAuditLogRepository` exist but are dead infrastructure — they are not connected to the enforcement path.
- **Evidence:**
  ```python
  # enforcement.py:405-456 — still routes to agent_feedback
  from src.database.models import AgentFeedback
  from src.database.repositories.agent_feedback_repo import AgentFeedbackRepository
  ...
  if entry.result == "deny":
      category = "bug"
      priority = "low"
  else:
      continue  # allow events silently skipped
  ...
  feedback_row = AgentFeedback(...)
  await repo.create(feedback_row)
  ```
- **Recommendation:** Update `_persist_audit_entries()` to import `AgentAuditLog` from `src.database.models` and `AgentAuditLogRepository` from `src.database.repositories.agent_audit_log_repo`. Map `AuditEntry.result` → `outcome` (`"allow"` / `"deny"`), persist both outcomes. Remove the `AgentFeedback` import from this method. Honor the `self._audit_allow_events` flag: when `True`, persist both outcomes; when `False`, persist only deny events for high-throughput deployments.

---

#### [MEDIUM] pgAdmin Default Password Falls Back to Hardcoded Weak Value

- **File:** `docker-compose.yml:239`
- **Category:** 3.1 Hardcoded Secrets / Weak Default Credentials
- **Description:** The pgAdmin service uses `${PGADMIN_DEFAULT_PASSWORD:-admin1234}` — if `PGADMIN_DEFAULT_PASSWORD` is not set in `.env`, the service starts with the plaintext password `admin1234`. The current `.env` file does not set this variable. pgAdmin exposes full PostgreSQL/TimescaleDB access via a web UI on port 5050.
- **Impact:** An attacker with network access to port 5050 (or any path that reaches it) could authenticate to pgAdmin with `admin1234`, gaining full DBA access to the database — including all trading data, account credentials, and API keys.
- **Evidence:**
  - `docker-compose.yml:239`: `PGADMIN_DEFAULT_PASSWORD: ${PGADMIN_DEFAULT_PASSWORD:-admin1234}`
  - `.env` (lines 1–44): `PGADMIN_DEFAULT_PASSWORD` is absent.
- **Recommendation:** Add `PGADMIN_DEFAULT_PASSWORD=<strong-random-value>` to `.env` and `.env.example`. Remove the `:-admin1234` default from `docker-compose.yml` so a missing env var causes the container to fail at startup rather than silently use a weak credential.

---

#### [LOW] Celery Broker/Backend Default URL Does Not Include Redis Password

- **File:** `src/tasks/celery_app.py:36`
- **Category:** 3.3 Configuration / Defense-in-Depth
- **Description:** The Celery app reads `REDIS_URL` from the environment with a default of `redis://redis:6379/0` (no password). The current `.env` sets `REDIS_URL` correctly with the password. However, the commented-out `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` in `.env` and `.env.example` both contain unauthenticated `redis://redis:6379/0` values. An operator who uncomments those lines to override the broker would inadvertently bypass Redis authentication.
- **Impact:** If the commented-out lines are uncommented without updating the URL to include the password, Celery workers would be denied by the authenticated Redis instance, causing task processing to fail. However, if a future configuration change relaxed Redis auth, this would expose Celery to an unauthenticated Redis.
- **Recommendation:** Update the commented examples in `.env` and `.env.example` to use the password-bearing URL format: `redis://:${REDIS_PASSWORD}@redis:6379/0`. Add an explanatory comment that the password must match `REDIS_PASSWORD`.

---

#### [LOW] RL deploy.py float(Decimal) Casts Are Documented but Not Isolated

- **File:** `agent/strategies/rl/deploy.py:235, 307, 342, 379, 397, 618, 627, 858`
- **Category:** 3.8 Input Validation / Financial Arithmetic
- **Description:** Multiple `float(Decimal)` and `float(price_dec)` conversions exist in `deploy.py` for numpy/SB3 interoperability. Most are commented with `# float() required for numpy/SB3 interop`, which is correct and expected. However, there is no centralized conversion helper, so future contributors may introduce naked `float(Decimal)` casts in financial logic paths without understanding the precision implications.
- **Impact:** Not currently a precision bug — the casts are at the numpy boundary, not at financial arithmetic boundaries. No immediate risk. However, the pattern creates a maintenance hazard.
- **Recommendation:** Consider extracting a `_to_float_for_numpy(val: Decimal) -> float` helper function in `deploy.py` that is explicitly called at the ML boundary. This isolates the unsafe conversion and makes it easy to audit. Tag it with a comment referencing the SB3 constraint.

---

### Per-Fix Verification Results

#### R2-01: ADMIN Role Check on grant_capability / set_role / revoke_capability

**Status: PASS**

Verified in `agent/permissions/capabilities.py`:

- `grant_capability()` (line 495): calls `await self.get_role(granted_by)`, then checks `ROLE_HIERARCHY.get(grantor_role, 0) < ROLE_HIERARCHY[AgentRole.ADMIN]`; raises `PermissionDenied` on failure. Cache is invalidated in `finally` block regardless of outcome.
- `set_role()` (line 711): identical ADMIN check before any DB mutation.
- `revoke_capability()` (line 594): raises `PermissionDenied` immediately if `granted_by is None` (fail-closed on missing grantor). Then performs identical ADMIN check.
- `get_role()` (line 804): on `AgentPermissionNotFoundError` or any DB error, returns `role_from_string(self._config.default_agent_role)` which is `"viewer"` (hierarchy 0). This is the documented fail-closed behavior — unknown grantors get viewer role, which is below ADMIN threshold.
- UUID validation is performed before the ADMIN check; `ValueError` is raised for malformed IDs.
- `PermissionDenied` is imported lazily from `agent.permissions.enforcement` to avoid circular imports.

No new vulnerabilities introduced. The ROLE_HIERARCHY comparison uses `>=` for ADMIN (hierarchy 3); no role with level < 3 can grant capabilities.

---

#### R2-02: Tracked create_task + BudgetManager.close() + AgentServer._shutdown() Wired

**Status: PASS**

Verified in `agent/permissions/budget.py`:

- `_pending_persists: set[asyncio.Task]` initialized at line 253.
- `record_trade()` (line 906): `asyncio.create_task(self._maybe_persist(agent_id))` — task added to set; `done_callback` removes it on completion.
- `check_and_record()` (line 993): same pattern.
- `close()` (line 1122): drains `_pending_persists` via `asyncio.gather(return_exceptions=True)`, logs individual task failures, logs completion. Safe to call on empty set.

Verified in `agent/server.py`:

- `_budget_manager` initialized in `_init_dependencies()` (line 428).
- `_shutdown()` (line 964–968): calls `await self._budget_manager.close()` inside a try/except that logs and continues on failure. This ensures pending counter snapshots are flushed before event loop teardown.

No `asyncio.ensure_future` found anywhere in `budget.py`. The fix is complete and correct.

---

#### R2-03: Redis --requirepass; No Host Port Binding; REDIS_PASSWORD in .env

**Status: PASS**

Verified in `docker-compose.yml`:

- Redis command (line 53–59): `--requirepass ${REDIS_PASSWORD}` is present.
- No `ports:` mapping on the `redis:` service — host port is not exposed at all. The comment explicitly states this is stronger than 127.0.0.1 binding.
- `env_file: .env` is set on the redis service, making `${REDIS_PASSWORD}` available.
- Healthcheck (line 70): `redis-cli -a ${REDIS_PASSWORD} ping` — authenticates correctly.
- All 5 consumer services (`api`, `ingestion`, `celery`, `celery-beat`, `agent`) use `env_file: .env` and inherit `REDIS_URL`.

Verified in `.env`:

- `REDIS_PASSWORD=JtClCsk5hDrvg8K0OexHwW9EYzzdNdHbnO9n_puNIjE` — present, non-empty, random-looking value.
- `REDIS_URL=redis://:JtClCsk5hDrvg8K0OexHwW9EYzzdNdHbnO9n_puNIjE@redis:6379/0` — password embedded, using internal hostname.

No unauthenticated Redis consumers found.

**Note:** The `.env` file contains production secrets and should not be committed to version control. Verify `.gitignore` excludes `.env` (`.env.example` is the committed template).

---

#### R2-04: AgentAuditLog Model + Migration 020 + Repository + enforcement.py Wired

**Status: PARTIAL FAIL — infrastructure created, wiring missing**

Verified as present:
- `src/database/models.py:3299`: `AgentAuditLog` class defined with correct columns (`id`, `agent_id`, `action`, `outcome`, `reason`, `trade_value`, `metadata`, `created_at`).
- `alembic/versions/020_add_agent_audit_log.py`: Migration creates the table with correct columns, CHECK constraint (`outcome IN ('allow', 'deny')`), and three indexes. `down_revision = "019"`, `revision = "020"`. Migration is correct.
- `src/database/repositories/agent_audit_log_repo.py`: Repository exists with `create()`, `bulk_create()`, `prune_old()`, `get_recent()`, `get_range()`, `get_outcome_counts()` methods. All use ORM `session.add()` — no injection risk.

Not verified:
- `enforcement.py._persist_audit_entries()` still imports `AgentFeedback` and `AgentFeedbackRepository`. `AgentAuditLog` and `AgentAuditLogRepository` are never imported in this file. Allow events are still silently dropped via `continue`. See HIGH finding above.

---

#### R2-05: verify_checksum strict=True Default on PPO.load() Call Sites

**Status: PASS**

Verified in `agent/strategies/checksum.py`:
- `verify_checksum(file_path: Path, *, strict: bool = True)` — default is `strict=True`.
- Missing sidecar with `strict=True` raises `SecurityError` (line 157). Digest mismatch always raises `SecurityError` regardless of `strict` flag.

Verified at all call sites:
- `agent/strategies/rl/deploy.py:541`: `verify_checksum(Path(self._model_path))` — no `strict=` argument, uses default `True`.
- `agent/strategies/rl/evaluate.py:386`: `verify_checksum(path)` — no `strict=` argument, uses default `True`.
- `agent/strategies/regime/classifier.py:391`: `verify_checksum(path)` — no `strict=` argument, uses default `True`.

No call site passes `strict=False`. The only occurrences of `strict=False` in the codebase are within the docstring comments of `checksum.py` itself.

---

#### R2-06: Checksum + Structure Validation Before joblib.load in classifier.py

**Status: PASS**

Verified in `agent/strategies/regime/classifier.py:368–435` (the `load()` classmethod):

1. `verify_checksum(path)` is called before `joblib.load(path)`. `SecurityError` is re-raised immediately, aborting the load.
2. Other exceptions during checksum verification are caught and logged as warnings, then execution proceeds to `joblib.load`. (This is a minor defense-in-depth concern: non-`SecurityError` checksum failures, e.g., `OSError` reading the sidecar, allow the load to proceed. However, the primary attack scenario — tampered file — is fully mitigated by the `SecurityError` re-raise.)
3. After `joblib.load()`, the payload type is checked: `if not isinstance(payload, dict): raise ValueError(...)`.
4. Required keys are validated: `required_keys = {"model", "label_encoder", "label_decoder", "feature_names", "seed", "backend"}` — 6 keys verified present before any access.

The structure check is more thorough than the R2-06 spec required (which mentioned only `"classifier"`).

---

#### R2-07: No --api-key argparse Definitions in Any Python Source

**Status: PASS**

Search result: `grep -rn "add_argument.*--api" agent/ src/ scripts/ --include="*.py"` returns only one match: `agent/strategies/regime/classifier.py:579: async def _train_cli(args: argparse.Namespace, *, api_key: str = "") -> None:` — this is a function signature that accepts an `api_key` keyword argument from an already-parsed `Namespace` object, not a new `--api-key` argument being added to a parser. The `api_key` is passed programmatically from within the CLI runner, not from `sys.argv`.

API keys are read from `agent/.env` via `AgentConfig` (pydantic-settings `BaseSettings`) across all strategy CLIs. No secrets are exposed in shell history or `ps` output.

---

#### R2-08: float(Decimal) Casts Fixed; RL Exceptions Documented

**Status: PASS with observation**

The original R2-08 fix targeted two issues:

1. **float(Decimal) casts in financial arithmetic paths** — Verified: budget.py uses `format(trade_value, "f")` for all `incrbyfloat` calls (lines 881, 970), not `float(Decimal)`. Decimal arithmetic is used throughout the budget check logic.

2. **RL exceptions documented** — The `deploy.py` file retains `float(Decimal)` at the numpy/SB3 boundary (lines 235, 307, 397, etc.) with inline comments explicitly noting `# float() required for numpy/SB3 interop`. These are not financial arithmetic boundaries; they are observation vector construction for the RL model. This is correct and documented behavior.

No unsafe `float(Decimal)` conversions found in financial paths (budget, order value, PnL calculation).

---

### Checks Performed (No Issues Found in Scope)

- **3.1 Hardcoded Secrets** — No hardcoded API keys, JWT tokens, or passwords in any reviewed fix file. Secrets sourced from `.env` / `os.environ` throughout.
- **3.2 Auth Bypass Paths** — No changes to `_PUBLIC_PATHS`, `_PUBLIC_PREFIXES`, or middleware order detected in the reviewed fix files.
- **3.3 SQL Injection** — All DB access in `agent_audit_log_repo.py`, `enforcement.py`, `capabilities.py`, and `budget.py` uses SQLAlchemy ORM `session.add()` / `select()` / parameterized queries. No f-string SQL construction found.
- **3.4 Agent Isolation** — `AgentAuditLogRepository` queries are correctly scoped by `agent_id` (`WHERE AgentAuditLog.agent_id == agent_id` on all read methods). Budget checks are scoped by `agent_id` throughout `budget.py`.
- **3.5 Rate Limit Coverage** — No new REST endpoints added by these fixes.
- **3.6 Sensitive Data in Logs** — Log statements in `capabilities.py` and `budget.py` log capability names, role values, and action strings. No API keys, passwords, or JWT tokens logged. Trade values are logged as `str(trade_value)` (Decimal string, not raw float).
- **3.7 Password Handling** — No password storage or comparison logic in any reviewed fix file.
- **3.8 Input Validation** — UUID validation is performed before any DB lookup in all three mutation methods of `capabilities.py`. Budget checks validate `Decimal` input type. Payload structure validation in `classifier.py.load()` prevents loading malformed deserialized objects.
- **3.11 Dependency Vulnerabilities** — `verify_checksum()` + structure check now fully guards `joblib.load()` in `classifier.py`. `PPO.load()` in `deploy.py` is guarded by `verify_checksum()`. No new `pickle`, `eval()`, `exec()`, `yaml.load()`, or `subprocess` patterns introduced.
- **3.12 Circuit Breaker** — Budget circuit breaker logic reviewed (fail-closed sentinel values confirmed in `_read_counters_from_db()`). No bypass paths introduced.

---

### Notes

1. **R2-04 is the only remaining open HIGH issue.** The infrastructure (model, migration, repository) is in place and production-ready. Only the 10–15 line change to `enforcement.py._persist_audit_entries()` is missing. This is a straightforward mechanical fix.

2. **Migration 020 head revision gap**: The `alembic/CLAUDE.md` still lists the current head as `019`. Migration `020` exists on disk and chains correctly (`down_revision = "019"`), but the CLAUDE.md inventory has not been updated. This is a documentation gap only, not a security issue.

3. **pgAdmin weak default password (MEDIUM)**: This pre-existed R2-03 and was not introduced by the fixes. However, the Redis auth fix drew attention to the overall infrastructure auth posture, which is why it is noted here. It is not a regression.

4. **The `enforce.py` `audit_allow_events` flag is wired but inert.** The constructor accepts `audit_allow_events: bool = True` and stores it in `self._audit_allow_events`. However, `_persist_audit_entries()` never reads this attribute — the `continue` on line 438 unconditionally skips all allow events regardless of flag value. This will need to be fixed simultaneously with the R2-04 wiring fix.
