---
name: agent/ tests are independent from platform tests/
description: agent/tests/ is fully independent from tests/ — different conftest, different pyproject.toml, no shared fixtures
type: project
---

The `agent/tests/` directory is independent from the platform's `tests/` directory.

**Why:** The agent package has its own `pyproject.toml` with `asyncio_mode = "auto"` and its own test suite that mocks the SDK client and httpx calls without needing a running platform. It does not use the platform conftest, app factory, or ORM factories.

**How to apply:** When running agent tests, run from the repo root with `pytest agent/tests/` (not from inside `agent/`). The root `pyproject.toml` picks up the asyncio mode setting. Similarly `tradeready-gym/tests/` runs from repo root with `pytest tradeready-gym/tests/`.
