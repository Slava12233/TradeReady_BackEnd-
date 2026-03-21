---
type: code-review
date: 2026-03-20
reviewer: security-reviewer
verdict: PASS WITH WARNINGS
scope: agent-strategies
tags:
  - review
  - security
  - strategies
---

# Security Review: agent/strategies/

**Date:** 2026-03-20
**Reviewer:** security-reviewer agent
**Branch:** V.0.0.2

## Files Reviewed

### rl/
- `agent/strategies/rl/config.py`
- `agent/strategies/rl/train.py`
- `agent/strategies/rl/deploy.py`
- `agent/strategies/rl/evaluate.py`
- `agent/strategies/rl/runner.py`
- `agent/strategies/rl/data_prep.py`

### evolutionary/
- `agent/strategies/evolutionary/config.py`
- `agent/strategies/evolutionary/genome.py`
- `agent/strategies/evolutionary/battle_runner.py`
- `agent/strategies/evolutionary/evolve.py`

### regime/
- `agent/strategies/regime/classifier.py`
- `agent/strategies/regime/switcher.py`
- `agent/strategies/regime/strategy_definitions.py`

### risk/
- `agent/strategies/risk/risk_agent.py`
- `agent/strategies/risk/middleware.py`

### ensemble/
- `agent/strategies/ensemble/config.py`
- `agent/strategies/ensemble/meta_learner.py`
- `agent/strategies/ensemble/run.py`
- `agent/strategies/ensemble/optimize_weights.py`
- `agent/strategies/ensemble/validate.py`
- `agent/strategies/ensemble/signals.py`

## CLAUDE.md Files Consulted

- `CLAUDE.md` (root)
- `agent/CLAUDE.md`
- `src/api/middleware/CLAUDE.md`
- `src/accounts/CLAUDE.md`

## Dependency Audit

The `agent/` package (`agent/pyproject.toml`) uses:
- `stable-baselines3` — PPO model loading (pickle-based internals)
- `scikit-learn` / `xgboost` — regime classifier (joblib serialization)
- `pydantic-settings` — configuration from env/`.env`
- `httpx` — async REST client
- `structlog` — structured logging

No `pip audit` run (agent has its own pyproject.toml separate from the platform). The serialization libraries (SB3, joblib) are the primary dependency risk vectors — see findings below.

---

## CRITICAL Issues (must fix before deploy)

None identified.

---

## HIGH Issues (fix soon)

### HIGH-1: Unsafe Deserialization — SB3 PPO Model Files (pickle)

**Files:**
- `agent/strategies/rl/deploy.py:538`
- `agent/strategies/rl/evaluate.py:382`
- `agent/strategies/rl/runner.py:272`
- `agent/strategies/ensemble/run.py:486`

**Category:** A8 — Insecure Deserialization (OWASP)

**Issue:** `PPO.load(path)` from `stable_baselines3` uses Python's `pickle` module internally (SB3 `.zip` files contain pickled policy weights and optimizer state). Loading a maliciously crafted `.zip` file will execute arbitrary Python code during deserialization. All four call sites accept user-supplied or auto-discovered paths with no integrity verification.

```python
# deploy.py:538
self._model = PPO.load(self._model_path)

# evaluate.py:382
models[label] = PPO.load(str(path))

# runner.py:272
model = PPO.load(model_path)

# ensemble/run.py:486
model = PPO.load(model_path_str)
```

**Impact:** An attacker who can write a file into the models directory (e.g., via a compromised CI artifact, shared filesystem, or supply-chain attack on a model repository) can execute arbitrary code on the host running the strategy. In a production environment this could lead to credential theft, data exfiltration, or lateral movement.

**Fix:** This is a known limitation of SB3/pickle. Apply defense-in-depth:

1. Restrict the models directory with filesystem permissions so only the training pipeline can write to it.
2. Compute and verify a SHA-256 checksum of each `.zip` file before loading. Store checksums out-of-band (e.g., in a separate signed manifest file checked into the repo). Add a helper:

```python
import hashlib

def _verify_model_checksum(path: Path, expected_sha256: str) -> None:
    """Raise ValueError if the file does not match the expected SHA-256."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise ValueError(
            f"Model file checksum mismatch for {path}. "
            f"Expected {expected_sha256}, got {digest}. "
            "Do not load — file may be tampered."
        )
```

3. Never load models from paths provided by end users at runtime. Restrict model paths to a known-good directory constant.

---

### HIGH-2: Unsafe Deserialization — joblib Regime Classifier

**Files:**
- `agent/strategies/regime/classifier.py:359`
- `agent/strategies/ensemble/run.py:550`

**Category:** A8 — Insecure Deserialization (OWASP)

**Issue:** `joblib.load(path)` deserializes arbitrary Python objects. `path` is accepted from the CLI `--model-path` argument with no path validation, no extension whitelist, and no checksum verification. After loading, the payload dict is used directly with no schema validation of its structure.

```python
# classifier.py:359
payload = joblib.load(path)
# Lines 360-365 use payload["model"], payload["feature_names"] etc. with no type checks
```

**Impact:** Same as HIGH-1 but for the regime classifier component. A malicious `.joblib` file triggers code execution during load.

**Fix:**
1. Validate that `path` ends with `.joblib` and is within an allowed models directory before calling `joblib.load`.
2. Compute and verify SHA-256 checksum before loading (same pattern as HIGH-1).
3. After loading, validate the payload structure before use:

```python
payload = joblib.load(path)
if not isinstance(payload, dict):
    raise ValueError(f"Unexpected joblib payload type: {type(payload)}")
required_keys = {"model", "feature_names", "label_encoder", "training_date"}
missing = required_keys - payload.keys()
if missing:
    raise ValueError(f"joblib payload missing keys: {missing}")
```

---

### HIGH-3: API Key Exposure via CLI Arguments

**Files:**
- `agent/strategies/rl/train.py` (line with `add_argument("--api-key")`)
- `agent/strategies/rl/deploy.py` (line with `add_argument("--api-key")`)
- `agent/strategies/rl/evaluate.py` (line with `add_argument("--api-key")`)
- `agent/strategies/rl/runner.py` (line with `add_argument("--api-key")`)
- `agent/strategies/rl/data_prep.py` (line with `add_argument("--api-key")`)
- `agent/strategies/regime/classifier.py` (line with `add_argument("--api-key")`)
- `agent/strategies/ensemble/run.py` (line with `add_argument("--api-key")`)
- `agent/strategies/ensemble/optimize_weights.py` (line with `add_argument("--api-key")`)

**Category:** A2 — Cryptographic Failures / Sensitive Data Exposure (OWASP)

**Issue:** All CLI entry points accept the platform API key via a `--api-key` command-line argument. Command-line arguments are visible in:
- The process list (`ps aux`, `/proc/*/cmdline`) to any user on the host
- Shell history files (`~/.bash_history`, `~/.zsh_history`)
- CI/CD log output if the command is echoed

**Impact:** Any local user or process on the host can read the `ak_live_...` key from the process table while the strategy script is running. The key grants full trading access to the associated agent.

**Fix:** Read the API key from an environment variable instead of a CLI argument. The `pydantic-settings` `BaseSettings` classes already support this pattern — the key just needs to be loaded from `agent/.env` or the environment rather than from `sys.argv`.

Replace the `--api-key` argument pattern across all scripts:

```python
# Instead of:
parser.add_argument("--api-key", required=True, help="Platform API key.")
# ...
config = RLConfig(platform_api_key=args.api_key)

# Do:
# Remove --api-key argument entirely.
# RLConfig() already reads RL_PLATFORM_API_KEY from agent/.env / environment.
config = RLConfig()
if not config.platform_api_key:
    parser.error(
        "Platform API key not set. "
        "Set RL_PLATFORM_API_KEY in agent/.env or as an environment variable."
    )
```

If a CLI override is genuinely needed (e.g., for testing), use an environment variable name as the value so the key itself never appears in argv:

```python
# Accept env var name, not the key value:
parser.add_argument(
    "--api-key-env",
    default="RL_PLATFORM_API_KEY",
    help="Name of environment variable containing the API key."
)
# Then: os.environ.get(args.api_key_env, "")
```

---

## MEDIUM Issues (should fix)

### MEDIUM-1: No Model File Path Validation (Path Traversal)

**Files:**
- `agent/strategies/rl/deploy.py` (model path from CLI `--model` arg)
- `agent/strategies/rl/evaluate.py` (model paths from CLI args)
- `agent/strategies/regime/classifier.py` (`--model-path` CLI arg)
- `agent/strategies/ensemble/config.py` (`rl_model_path`, `evolved_genome_path`, `regime_model_path` fields)

**Category:** A5 — Security Misconfiguration / Path Traversal

**Issue:** Model file paths are accepted from CLI arguments or config fields with no validation that the path is within an allowed directory. An operator running these scripts with a maliciously constructed path (e.g., `../../etc/passwd`) would get an error, but more relevant is that no constraint prevents loading model files from unintended locations outside the project tree.

**Fix:** Resolve the path and assert it is within the expected models directory:

```python
MODELS_DIR = Path(__file__).parent / "models"

def _validate_model_path(path: Path, suffix: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(MODELS_DIR.resolve()):
        raise ValueError(
            f"Model path {path} is outside the allowed models directory {MODELS_DIR}."
        )
    if resolved.suffix != suffix:
        raise ValueError(f"Expected {suffix} file, got {resolved.suffix}.")
    return resolved
```

---

### MEDIUM-2: Auto-Discovery Loads First Available Model Without Verification

**Files:**
- `agent/strategies/rl/evaluate.py` (auto-discovers all `ppo_seed*.zip` files in `models/`)
- `agent/strategies/ensemble/run.py:474` (auto-discovers `ppo_seed*.zip` files)

**Category:** A8 — Insecure Deserialization

**Issue:** When no explicit model path is configured, the code globs for matching `.zip` files and loads the first one found. This means any `.zip` file placed in the models directory that matches the glob pattern will be loaded automatically, including files dropped by an attacker.

```python
# ensemble/run.py:474
found = sorted(default_dir.glob("ppo_seed*.zip"))
if found:
    model_path_str = str(found[0])
```

**Impact:** Reduces the bar for the deserialization attack in HIGH-1 — the attacker only needs to place a `.ppo_seed_malicious.zip` file matching the glob, not replace a specific known file.

**Fix:** Only load the specific expected filename (`ppo_seed42.zip`) by default. Do not fall back to loading any other matching file from the directory without an explicit checksum match.

---

### MEDIUM-3: base_url Not Validated as HTTP/HTTPS (Potential SSRF)

**Files:**
- `agent/strategies/rl/deploy.py` (`--base-url` CLI arg)
- `agent/strategies/rl/runner.py` (`--base-url` CLI arg)
- `agent/strategies/rl/data_prep.py` (`--data-url` CLI arg)
- `agent/strategies/evolutionary/battle_runner.py` (reads from `AgentConfig.platform_base_url`)
- `agent/strategies/ensemble/run.py` (`--base-url` CLI arg)
- `agent/strategies/ensemble/optimize_weights.py` (`--base-url` CLI arg)

**Category:** A10 — Server-Side Request Forgery (SSRF)

**Issue:** The `base_url` / `data_url` values accepted from CLI arguments or config are passed directly to `httpx.AsyncClient(base_url=...)` without validating that the scheme is `http://` or `https://`. This could allow internal network scanning or unexpected protocol usage if the value is set to `file://`, `ftp://`, or an internal RFC-1918 address by a misconfigured deployment or in a shared environment.

**Fix:** Add a URL scheme validator to the `BaseSettings` config classes and CLI argument parsers:

```python
from urllib.parse import urlparse

def _validate_url(url: str, field_name: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"{field_name} must use http:// or https:// scheme, got: {url!r}"
        )
    return url
```

For `pydantic-settings` fields, add a `@field_validator`:

```python
@field_validator("platform_base_url")
@classmethod
def validate_base_url(cls, v: str) -> str:
    return _validate_url(v, "platform_base_url")
```

---

## LOW Issues (consider)

### LOW-1: HTTP Response Body Included in Log Messages

**Files:**
- `agent/strategies/evolutionary/battle_runner.py:279`

**Category:** A9 — Security Logging and Monitoring Failures

**Issue:** HTTP error response bodies are logged truncated to 200 characters:

```python
exc.response.text[:200]
```

Server-side error responses may include internal details such as stack traces, query fragments, internal hostnames, or partial data from other requests. These details appear in structured log output which may be stored or forwarded to log aggregators.

**Fix:** Log only the HTTP status code and a safe summary string rather than server-side response body content. If the body is needed for debugging, log it at `DEBUG` level only when explicitly enabled:

```python
log.warning(
    "battle_runner.http_error",
    status_code=exc.response.status_code,
    url=str(exc.request.url),
    # Do not include exc.response.text
)
```

---

### LOW-2: Empty String Default for API Key Fields (Silent Auth Failure)

**Files:**
- `agent/strategies/rl/config.py` (`platform_api_key: str = Field(default="")`)
- `agent/strategies/ensemble/config.py` (`platform_api_key: str = Field(default="")`)

**Category:** A2 — Sensitive Data Exposure (misconfiguration)

**Issue:** The API key fields default to empty string `""`. If an operator forgets to set the key in `agent/.env` or the environment, the scripts will construct HTTP requests with `X-API-Key: ` (an empty header value). The platform will reject these with a 401 but only at runtime — there is no eager validation at startup.

`train.py` does check for an empty key and exits (lines 219-222), but `deploy.py` and `ensemble/run.py` do not have the same guard.

**Fix:** Add a `@field_validator` to the config classes that raises `ValueError` for empty API key values:

```python
@field_validator("platform_api_key")
@classmethod
def validate_api_key(cls, v: str) -> str:
    if not v:
        raise ValueError(
            "platform_api_key is required. "
            "Set RL_PLATFORM_API_KEY in agent/.env or as an environment variable."
        )
    return v
```

Or, if an empty key is intentionally allowed for read-only/public endpoints, document this explicitly and add the guard only in scripts that place orders.

---

### LOW-3: Exception Detail Included in Error Field of Step Results

**Files:**
- `agent/strategies/risk/middleware.py:618`

**Category:** A9 — Security Logging and Monitoring Failures

**Issue:** Python exception strings are included in structured step result fields and log messages:

```python
f"Error during portfolio assessment: {error}"
```

Exception messages can contain internal class names, file paths, query fragments, or other diagnostic details that reveal implementation internals. These fields propagate into `StepResult.error` which is included in `EnsembleReport` output files.

**Fix:** Log the full exception at `DEBUG` or `ERROR` level internally but return a generic sanitized message in any externally visible result field:

```python
log.error("risk_middleware.portfolio_assessment_error", exc_info=True)
return VetoDecision(verdict="HALT", reason="Internal error during portfolio assessment.")
```

---

## Passed Checks

| Check | Status | Notes |
|-------|--------|-------|
| No hardcoded API keys or secrets | PASS | All secrets loaded from `agent/.env` via `pydantic-settings` with appropriate env-var prefixes (`RL_`, `EVO_`, `RISK_`, `ENSEMBLE_`) |
| No cross-agent data leakage | PASS | `battle_runner.py` maintains strict per-agent mapping (`self._agent_ids[i]`); JWT tokens are per-agent and not shared |
| No code execution in genome definitions | PASS | `StrategyGenome.to_strategy_definition()` produces a plain `dict`; `from_vector()` uses numpy clipping and Pydantic validation only |
| No raw SQL / injection in REST calls | PASS | All HTTP calls use `httpx` with structured URL paths and JSON bodies; no string concatenation into query parameters |
| API keys not logged | PASS | No `log.*` calls include `api_key`, `token`, `secret`, or `password` values in any strategy file |
| JWT acquisition secure | PASS | `battle_runner._acquire_jwt()` POSTs credentials from `AgentConfig` (env/`.env`), stores JWT in `self._jwt_token` (not logged) |
| Symbol input validated | PASS | `risk_agent.py` validates symbols against `_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}$")` before processing |
| Evolved genome JSON deserialization safe | PASS | `ensemble/run.py:504` uses `json.loads()` + `StrategyGenome(**genome_data)` — Pydantic validates all fields; no `pickle`/`joblib` involved |
| Risk middleware fails closed | PASS | Pipeline errors return `verdict="HALT"` — orders are blocked on any unexpected error, not silently approved |
| Config validation on numeric bounds | PASS | All numeric config fields use Pydantic `ge`/`le` constraints; `confidence_threshold`, `min_agreement_rate`, `risk_base_size_pct` are all bounded |
| No `eval()` / `exec()` / `__import__` with user data | PASS | No dynamic code execution found anywhere in the strategy codebase |
| No `subprocess` with user-supplied arguments | PASS | No shell commands are constructed from user input |

---

## Overall Assessment: CONDITIONAL PASS

The strategy codebase has **no critical vulnerabilities** and follows good security hygiene in most areas: secrets are loaded from environment variables, logs contain no credentials, agent isolation is maintained, and all computation uses safe data structures with Pydantic validation.

The HIGH findings (unsafe deserialization of pickle/joblib ML artifacts and API key CLI exposure) are systemic issues common across all strategy sub-packages. They represent real risk in a shared or production environment but are mitigated in practice by:
- The model files are locally generated artifacts (not downloaded from untrusted sources today)
- The CLI scripts are internal tools, not user-facing services

**Before promoting these strategies to a production deployment or shared infrastructure, the following must be addressed:**

1. **HIGH-1 + HIGH-2**: Implement SHA-256 checksum verification for all model files before loading (`PPO.load`, `joblib.load`).
2. **HIGH-3**: Remove `--api-key` CLI arguments and source all platform credentials exclusively from environment variables or `agent/.env`.

The MEDIUM and LOW findings are good-practice improvements but do not block deployment of these components in the current controlled environment (local developer workstation, CI pipeline with restricted access).
