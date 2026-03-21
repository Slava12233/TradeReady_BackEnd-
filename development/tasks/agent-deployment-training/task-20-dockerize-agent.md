---
task_id: 20
title: "Create agent Dockerfile & compose service"
type: task
agent: "backend-developer"
phase: 10
depends_on: [1]
status: "completed"
board: "[[agent-deployment-training/README]]"
priority: "low"
files: ["agent/Dockerfile", "docker-compose.yml"]
tags:
  - task
  - deployment
  - training
---

# Task 20: Create agent Dockerfile & compose service

## Assigned Agent: `backend-developer`

## Objective
Containerize the agent package so it can run as a Docker service alongside the platform.

## Files to Create/Modify
1. Create `agent/Dockerfile`:
   - Base: `python:3.12-slim`
   - Copy `sdk/`, `tradeready-gym/`, `agent/`
   - Install all packages with `pip install -e`
   - Default CMD: `python -m agent.main all`

2. Add to `docker-compose.yml`:
   - New `agent` service
   - Depends on `api` (healthy)
   - Reads from `agent/.env`
   - Volumes for reports and model artifacts

## Acceptance Criteria
- [ ] `docker build -f agent/Dockerfile .` succeeds
- [ ] Agent container starts and connects to platform API
- [ ] Smoke test passes inside container
- [ ] Model artifacts persist via volume mount
- [ ] Reports accessible from host via volume mount

## Dependencies
- Task 01: ML dependencies declared

## Agent Instructions
Read `docker-compose.yml` for existing service patterns. The agent needs network access to the `api` service (use `internal` network). Don't include the GPU runtime by default — add as a comment for users with NVIDIA GPUs.

## Estimated Complexity
Medium — Dockerfile + compose integration + volume mapping.
