---
task_id: 28
title: "Migrate 6 files from stdlib logging to structlog"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: []
tags:
  - task
  - backend
  - logging
  - P2
---

# Task 28: Migrate stdlib logging to structlog

## Assigned Agent: `backend-developer`

## Objective
6 files use stdlib `logging` instead of the project-standard `structlog`. This means their log messages don't include trace_id correlation or structured JSON output.

## Context
Code standards review (SR-04) flagged this. The project uses structlog throughout, but 6 files were missed in the migration.

## Files to Modify
- Find by grepping: `import logging` (but not `structlog`) in `src/`
- Replace `logging.getLogger()` with `structlog.get_logger()`
- Update log calls to use structlog's keyword argument style

## Acceptance Criteria
- [ ] Zero files in `src/` use stdlib `logging.getLogger()` (except structured log configuration)
- [ ] All migrated files use `structlog.get_logger()`
- [ ] Log messages use keyword arguments for structured data
- [ ] Existing log messages are preserved (content, not format)

## Agent Instructions
1. Grep for `import logging` in `src/` (exclude `__init__.py` log config files)
2. For each file, replace `import logging` with `import structlog`
3. Replace `logger = logging.getLogger(__name__)` with `logger = structlog.get_logger(__name__)`
4. Replace `logger.info("msg %s", val)` with `logger.info("msg", key=val)`

## Estimated Complexity
Low — mechanical find-and-replace across 6 files
