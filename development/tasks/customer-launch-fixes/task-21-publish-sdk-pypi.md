---
task_id: 21
title: "Publish SDK to PyPI"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["sdk/pyproject.toml", "sdk/README.md", ".github/workflows/publish-sdk.yml"]
tags:
  - task
  - sdk
  - pypi
  - distribution
  - P1
---

# Task 21: Publish SDK to PyPI

## Assigned Agent: `backend-developer`

## Objective
The Python SDK is not published to PyPI. `pip install tradeready` fails. Developers can't easily install the SDK.

## Context
Marketing readiness audit (SR-11) flagged this as P1. The SDK is the primary developer onboarding tool — if `pip install` doesn't work, developers won't try the platform.

## Files to Modify
- `sdk/pyproject.toml` — Verify package metadata (name, version, description, author, URLs)
- `sdk/README.md` — Ensure it serves as the PyPI landing page
- `.github/workflows/publish-sdk.yml` — Create CI workflow for PyPI publishing on tag

## Acceptance Criteria
- [ ] SDK package metadata is complete (name: `tradeready`, version, description, classifiers)
- [ ] `pip install tradeready` works from PyPI (or TestPyPI for initial validation)
- [ ] README renders correctly on PyPI
- [ ] CI workflow publishes to PyPI on version tag (e.g., `sdk-v0.1.0`)
- [ ] Package includes all necessary files (py.typed, LICENSE)

## Agent Instructions
1. Read `sdk/CLAUDE.md` for SDK structure
2. Verify pyproject.toml has all required PyPI fields
3. Create a GitHub Actions workflow that publishes on tag push
4. Use `pypa/gh-action-pypi-publish` action for secure publishing
5. First publish to TestPyPI to validate, then switch to production PyPI

## Estimated Complexity
Medium — packaging + CI workflow
