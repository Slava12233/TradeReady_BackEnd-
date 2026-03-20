---
task_id: 17
title: "Documentation update (CLAUDE.md, README)"
agent: "doc-updater"
phase: 6
depends_on: [16]
status: "completed"
priority: "low"
files:
  - "agent/CLAUDE.md"
  - "CLAUDE.md"
---

# Task 17: Documentation update

## Assigned Agent: `doc-updater`

## Objective
Create `agent/CLAUDE.md` for the new package and update the root `CLAUDE.md` to reference the agent module.

## Files to Create/Modify

### Create `agent/CLAUDE.md`
- Module purpose (platform testing agent)
- Directory structure and file inventory
- Key classes and functions
- Configuration (env vars)
- Usage patterns (CLI commands)
- Dependencies (pydantic-ai, SDK, httpx)

### Update root `CLAUDE.md`
- Add `agent/CLAUDE.md` to the CLAUDE.md Index table under "Infrastructure & Other"
- Add agent-related env vars to the Environment Variables table
- Update the "How to Start" section if needed

## Acceptance Criteria
- [ ] `agent/CLAUDE.md` exists with complete module documentation
- [ ] Root `CLAUDE.md` references `agent/CLAUDE.md` in the index
- [ ] Usage instructions are accurate (CLI commands match implementation)
- [ ] Environment variables documented

## Dependencies
- Task 16 (E2E test must pass — confirms everything works)

## Agent Instructions
- Follow the pattern of existing CLAUDE.md files (e.g., `sdk/CLAUDE.md`)
- Include the directory structure from the plan
- Document all CLI commands with examples
- List all environment variables

## Estimated Complexity
Low — documentation creation following existing patterns
