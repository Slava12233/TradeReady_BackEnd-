---
task_id: 9
title: "Add request deduplication to API client"
type: task
agent: "frontend-developer"
phase: 2
depends_on: []
status: "completed"
board: "[[frontend-performance-fixes/README]]"
priority: "high"
files:
  - "Frontend/src/lib/api-client.ts"
tags:
  - task
  - frontend
  - performance
---

# Task 9: Add Request Deduplication to API Client

## Assigned Agent: `frontend-developer`

## Objective

Add an in-flight request map to the API client so that identical concurrent requests are deduplicated — only one network request fires, and all callers receive the same response.

## Context

The API client is a raw `fetch()` wrapper with no deduplication. When 3 components mount simultaneously and call the same endpoint, 3 identical HTTP requests fire. TanStack Query deduplicates at the query level, but direct API calls have no protection.

From the performance review (C4): "No request deduplication in API client — causes waterfall queries."

## Files to Modify

- `Frontend/src/lib/api-client.ts` (lines 92-162):
  - Add a `Map<string, Promise<Response>>` for in-flight GET requests
  - Key by `method + url + sorted params`
  - On request start: check if in-flight, return existing promise if so
  - On request complete (success or error): remove from map
  - Only deduplicate GET requests (POST/PUT/DELETE should never be deduped)
  - Also fix: `MAX_RETRIES = 1` should be `3` and use exponential backoff (match JSDoc)
  - Also fix: `REQUEST_TIMEOUT_MS = 4_000` should match JSDoc or update JSDoc

## Acceptance Criteria

- [ ] Concurrent identical GET requests result in only 1 network request
- [ ] All callers receive the same response data
- [ ] POST/PUT/DELETE requests are NOT deduplicated
- [ ] In-flight map is cleaned up on both success and error
- [ ] Retry logic uses exponential backoff (200ms, 400ms, 800ms) for up to 3 retries
- [ ] JSDoc comments match actual implementation
- [ ] No TypeScript errors
- [ ] `pnpm build` passes

## Agent Instructions

1. Read `Frontend/src/lib/api-client.ts` fully
2. Add a module-level `const inFlightRequests = new Map<string, Promise<any>>()`
3. In the `request()` function, for GET requests:
   - Generate cache key from method + URL + sorted query params
   - If key exists in map, return the existing promise
   - Otherwise, create the promise, store it, and remove on settle
4. Fix retry count and backoff to match documentation
5. Update JSDoc to reflect actual behavior

## Estimated Complexity

Medium — requires careful promise handling and cleanup
