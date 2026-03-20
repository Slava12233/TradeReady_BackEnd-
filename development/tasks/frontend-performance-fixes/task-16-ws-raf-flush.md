---
task_id: 16
title: "Switch WebSocket price flush to requestAnimationFrame"
agent: "frontend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "medium"
files:
  - "Frontend/src/hooks/use-websocket.ts"
---

# Task 16: Switch WebSocket Price Flush to requestAnimationFrame

## Assigned Agent: `frontend-developer`

## Objective

Replace `setTimeout`-based price batch flushing with `requestAnimationFrame` (with a 100ms minimum interval) for smoother visual updates, and fix the buffer cleanup on unmount.

## Context

The price batch buffer flushes every 100ms via `setTimeout`, which may fire out of sync with the browser's frame rate. Also, `priceBufRef.current` is never nullified on destroy, risking stale flushes after unmount.

From the performance review (M7): "WS buffer uses setTimeout not rAF" and "Buffer not nullified on destroy."

## Files to Modify

- `Frontend/src/hooks/use-websocket.ts` (PriceBatchBuffer class, lines 35-74):
  - Replace `setTimeout` with `requestAnimationFrame` for the flush schedule
  - Keep 100ms minimum interval check (compare `performance.now()`)
  - Nullify buffer reference on destroy
  - Add mounted guard before flushing to store
  - Deduplicate batch entries: use `Map<symbol, price>` instead of array

## Acceptance Criteria

- [ ] Price updates are flushed via `requestAnimationFrame`
- [ ] Minimum 100ms between flushes is maintained
- [ ] Buffer is nullified on component unmount
- [ ] No flush fires after component unmount
- [ ] Same symbol updated multiple times within a batch window only keeps latest price
- [ ] Price updates still display correctly in the UI
- [ ] `pnpm build` passes

## Agent Instructions

1. Read `Frontend/src/hooks/use-websocket.ts` fully
2. Refactor `PriceBatchBuffer` to use rAF with a timestamp check
3. Add `this.mounted = false` flag in `destroy()`, check before flush
4. Change batch storage from array to `Map<string, string>` for deduplication

## Estimated Complexity

Medium — requires careful timing and cleanup logic
