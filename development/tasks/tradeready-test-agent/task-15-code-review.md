---
task_id: 15
title: "Code review of full agent package"
agent: "code-reviewer"
phase: 6
depends_on: [13]
status: "completed"
priority: "medium"
files: []
---

# Task 15: Code review of full agent package

## Assigned Agent: `code-reviewer`

## Objective
Review the entire `agent/` package for compliance with project standards, code quality, security, and architectural consistency.

## Review Scope
- All files in `agent/` directory
- Focus areas:
  - Code standards: typing, docstrings, naming conventions
  - Security: API key handling, no hardcoded secrets, proper error handling
  - Architecture: clean separation of concerns, proper imports
  - Pydantic AI patterns: correct tool registration, output types, agent configuration
  - Async correctness: proper await, no blocking calls
  - Error handling: no bare except, descriptive error messages

## Acceptance Criteria
- [ ] Review report generated at `development/code-reviews/agent-package-review.md`
- [ ] All critical issues flagged
- [ ] Security concerns around API key handling reviewed
- [ ] Async patterns validated
- [ ] No violations of project code standards

## Dependencies
- Task 13 (full package must be complete to review)

## Agent Instructions
- Read root `CLAUDE.md` for project code standards
- Review every `.py` file in `agent/`
- Pay special attention to secret handling (API keys should only come from env)
- Check that all async functions properly await
- Verify tool functions have proper docstrings (used as LLM tool descriptions)

## Estimated Complexity
Medium — full package review
