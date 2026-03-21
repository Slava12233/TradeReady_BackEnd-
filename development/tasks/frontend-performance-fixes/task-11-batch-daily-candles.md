---
task_id: 11
title: "Batch useDailyCandlesBatch into groups of 50 symbols"
type: task
agent: "frontend-developer"
phase: 2
depends_on: []
status: "completed"
board: "[[frontend-performance-fixes/README]]"
priority: "high"
files:
  - "Frontend/src/hooks/use-market-data.ts"
tags:
  - task
  - frontend
  - performance
---

# Task 11: Batch useDailyCandlesBatch into Groups of 50 Symbols

## Assigned Agent: `frontend-developer`

## Objective

Refactor `useDailyCandlesBatch` to batch symbols into groups of 50 instead of creating one TanStack Query per symbol. This reduces 600 individual query entries to ~12.

## Context

Currently, `useDailyCandlesBatch` creates a separate TanStack query for every symbol in the array. With 600+ symbols, this means 600 individual cache entries and potentially 600 network requests.

From the performance review (H6): "useDailyCandlesBatch creates per-symbol queries — 600 queries instead of 6-12 batches."

## Files to Modify

- `Frontend/src/hooks/use-market-data.ts` (lines 208-237):
  - Chunk the symbol array into groups of 50
  - Use `useQueries()` with one query per batch (not per symbol)
  - Merge results into a single flat map for consumers
  - Add `keepPreviousData` / `placeholderData` to prevent loading flashes

## Acceptance Criteria

- [ ] Symbols are grouped into batches of 50
- [ ] Only ~12 queries fire instead of 600
- [ ] Results are merged into the same shape as before (consumers don't need changes)
- [ ] `placeholderData: keepPreviousData` prevents loading flashes
- [ ] Market table still shows daily candle data correctly
- [ ] No TypeScript errors
- [ ] `pnpm build` passes

## Agent Instructions

1. Read `Frontend/src/hooks/use-market-data.ts` — focus on the `useDailyCandlesBatch` implementation
2. Check if the backend endpoint supports multiple symbols in one request. If yes, batch into a single request per group. If not, still group the TanStack queries to limit concurrency.
3. Use a chunking utility: `symbols.reduce((batches, sym, i) => { const idx = Math.floor(i / 50); (batches[idx] ??= []).push(sym); return batches; }, [] as string[][])`
4. Ensure consumers of this hook get the same return type

## Estimated Complexity

Medium — requires refactoring query structure while maintaining API compatibility
