---
task_id: E-07
title: "Add dependency caching"
type: task
agent: "backend-developer"
track: E
depends_on: ["E-02"]
status: "completed"
priority: "medium"
board: "[[april-2026-execution/README]]"
files: [".github/workflows/test.yml"]
tags:
  - task
  - ci
  - performance
---

# Task E-07: Add dependency caching

## Assigned Agent: `backend-developer`

## Objective
Add `actions/cache` for pip (`~/.cache/pip`) and npm (`~/.npm`) to speed up CI runs.

## Files to Modify
- `.github/workflows/test.yml`

## Acceptance Criteria
- [ ] pip cache configured with `actions/cache` using `requirements.txt` or `pyproject.toml` as key
- [ ] npm cache configured (or use `actions/setup-node` with `cache: 'npm'`)
- [ ] Cache hit reduces install time by 50%+
- [ ] Cache keys include lockfile hash for proper invalidation

## Dependencies
- **E-02**: Basic CI structure must be in place

## Agent Instructions
For pip caching:
```yaml
- uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements*.txt', '**/pyproject.toml') }}
    restore-keys: ${{ runner.os }}-pip-
```
For npm, use the built-in cache in `actions/setup-node`:
```yaml
- uses: actions/setup-node@v4
  with:
    node-version: '20'
    cache: 'npm'
    cache-dependency-path: Frontend/package-lock.json
```

## Estimated Complexity
Low — standard CI caching patterns.
