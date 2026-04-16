---
task_id: 27
title: "Fix cache._redis private access in account.py"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["src/accounts/service.py", "src/cache/price_cache.py"]
tags:
  - task
  - backend
  - code-quality
  - P2
---

# Task 27: Fix cache._redis private access

## Assigned Agent: `backend-developer`

## Objective
`account.py` accesses the private `cache._redis` attribute, bypassing the cache module's error handling and abstraction layer.

## Context
Code standards review (SR-04) flagged this. Using private attributes breaks encapsulation and skips error handling that the public API provides.

## Files to Modify
- `src/accounts/service.py` — Replace `cache._redis` with public cache API calls
- `src/cache/price_cache.py` — Add public methods if needed for the operations account.py needs

## Acceptance Criteria
- [ ] No references to `cache._redis` outside the cache module
- [ ] Account service uses public cache API methods
- [ ] Error handling from cache module applies to these calls
- [ ] Existing functionality unchanged

## Agent Instructions
1. Grep for `_redis` in `src/accounts/` to find the private access
2. Understand what operations are being performed
3. Either use existing public cache methods or add new ones to the cache module
4. Replace the private access with public API calls

## Estimated Complexity
Low — refactor to use public API
