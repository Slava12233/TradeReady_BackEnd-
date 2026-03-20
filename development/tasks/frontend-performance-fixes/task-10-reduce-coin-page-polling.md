---
task_id: 10
title: "Reduce coin detail page polling frequency"
agent: "frontend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
files:
  - "Frontend/src/hooks/use-market-data.ts"
---

# Task 10: Reduce Coin Detail Page Polling Frequency

## Assigned Agent: `frontend-developer`

## Objective

Reduce aggressive polling on the coin detail page from 6+ requests per 10 seconds to a more reasonable level, and disable REST price polling when WebSocket is connected.

## Context

The coin detail page runs 4 concurrent polling intervals: orderbook (5s), recent trades (10s), candles (30s), and REST prices (30s). This generates excessive network traffic, especially since WS already provides real-time prices.

From the performance review (H2): "Coin page 6+ requests per 10s" and (M1): "REST polling concurrent with WS."

## Files to Modify

- `Frontend/src/hooks/use-market-data.ts`:
  - `useOrderbook()` (line 143): Change `refetchInterval` from `5_000` to `15_000`
  - `useRecentTrades()` (line 128): Change `refetchInterval` from `10_000` to `30_000`
  - `useAllPrices()` (lines 54-61): Add `enabled` check that disables REST polling when WS is connected
  - Consider adding a `useIsWsConnected()` check from the WebSocket store

## Acceptance Criteria

- [ ] Orderbook polls every 15s instead of 5s
- [ ] Recent trades polls every 30s instead of 10s
- [ ] REST price polling disabled when WebSocket is connected
- [ ] REST price polling re-enables as fallback when WS disconnects
- [ ] Coin detail page still shows live data correctly
- [ ] No TypeScript errors

## Agent Instructions

1. Read `Frontend/src/hooks/use-market-data.ts` fully
2. Read `Frontend/src/stores/websocket-store.ts` for the WS connection status selector
3. For `useAllPrices()`, use the WS connection status to conditionally enable/disable REST polling:
   ```tsx
   const isWsConnected = useWebSocketStore(selectConnectionStatus) === "connected";
   // ... in query config:
   refetchInterval: isWsConnected ? false : QUERY_CONFIG.marketStaleTime,
   ```
4. Reduce other intervals as specified
5. Verify the coin detail page still functions with reduced polling

## Estimated Complexity

Low-Medium — interval changes + conditional polling logic
