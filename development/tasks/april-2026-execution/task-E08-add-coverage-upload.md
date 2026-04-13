---
task_id: E-08
title: "Add coverage upload"
type: task
agent: "backend-developer"
track: E
depends_on: ["E-02"]
status: "completed"
priority: "low"
board: "[[april-2026-execution/README]]"
files: [".github/workflows/test.yml", "README.md"]
tags:
  - task
  - ci
  - coverage
---

# Task E-08: Add coverage upload

## Assigned Agent: `backend-developer`

## Objective
Upload pytest coverage as a CI artifact and optionally add a coverage badge to the README.

## Files to Modify
- `.github/workflows/test.yml` — add coverage artifact upload
- `README.md` — add coverage badge (optional)

## Acceptance Criteria
- [ ] `pytest --cov=src --cov-report=xml` generates coverage report
- [ ] Coverage XML uploaded as GitHub Actions artifact
- [ ] Artifact retained for 30 days
- [ ] Coverage badge added to README (optional — can use shields.io or codecov)

## Dependencies
- **E-02**: Integration test job must exist

## Agent Instructions
Add coverage generation to the unit test job:
```yaml
- run: pytest --cov=src --cov-report=xml --cov-report=html
- uses: actions/upload-artifact@v4
  with:
    name: coverage-report
    path: |
      coverage.xml
      htmlcov/
    retention-days: 30
```
For a badge, consider Codecov integration or a simple shields.io dynamic badge.

## Estimated Complexity
Low — standard CI artifact upload.
