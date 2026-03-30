---
task_id: 6
title: "CORS env-driven configuration"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "high"
board: "[[deployment-v002/README]]"
files: ["src/config.py", "src/main.py", ".env.example", ".env"]
tags:
  - task
  - cors
  - deployment
---

# Task 06: CORS env-driven configuration

## Assigned Agent: `backend-developer`

## Status: COMPLETED
- Added `cors_origins` field to `Settings` class in `src/config.py`
- Replaced hardcoded localhost origins in `src/main.py` with env-driven `CORS_ORIGINS`
- Updated `.env.example` and `.env` with `CORS_ORIGINS` field
