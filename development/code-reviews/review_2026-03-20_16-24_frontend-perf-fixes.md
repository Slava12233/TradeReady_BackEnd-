---
type: code-review
date: 2026-03-20
reviewer: code-reviewer
verdict: NEEDS FIXES
scope: frontend-perf-fixes
tags:
  - review
  - frontend
  - performance
---

# Code Review Report

- **Date:** 2026-03-20 16:24
- **Reviewer:** code-reviewer agent
- **Verdict:** NEEDS FIXES

## Files Reviewed

- `Frontend/src/components/market/market-table-row.tsx`
- `Frontend/src/hooks/use-portfolio.ts`
- `Frontend/src/hooks/use-price.ts`
- `Frontend/src/components/ui/chart.tsx`
- `Frontend/src/app/(dashboard)/battles/loading.tsx`
- `Frontend/next.config.ts`
- `Frontend/src/app/(dashboard)/layout.tsx`
- `Frontend/src/components/layout/header.tsx`
- `Frontend/src/components/layout/sidebar.tsx`
- `Frontend/src/app/(dashboard)/dashboard/page.tsx`
- `Frontend/src/lib/api-client.ts`
- `Frontend/src/hooks/use-market-data.ts`
- `Frontend/src/app/globals.css`
- `Frontend/src/styles/landing.css`
- `Frontend/src/components/shared/section-error-boundary.tsx`
- `Frontend/src/lib/prefetch.ts`
- `Frontend/src/hooks/use-websocket.ts`
- `Frontend/tests/unit/components/price-flash-cell.test.tsx`
- `Frontend/tests/unit/api-client.test.ts`

## CLAUDE.md Files Consulted

- `Frontend/CLAUDE.md`
- `Frontend/src/components/CLAUDE.md`
- `Frontend/src/components/market/CLAUDE.md`
- `Frontend/src/components/layout/CLAUDE.md`
- `Frontend/src/components/shared/CLAUDE.md`
- `Frontend/src/components/ui/CLAUDE.md`
- `Frontend/src/hooks/CLAUDE.md`
- `Frontend/src/lib/CLAUDE.md`
- `Frontend/src/app/CLAUDE.md`
- `Frontend/src/stores/CLAUDE.md`
- `Frontend/src/styles/CLAUDE.md`

---

## Critical Issues (must fix)

### 1. `globals.css` landing CSS extraction is incomplete — file is still 1089 lines

- **File:** `Frontend/src/app/globals.css`
- **Rule violated:** Performance standard — the whole point of this task was to reduce globals.css from 1090 → 279 lines by moving landing CSS to `landing.css`. The `development/context.md` entry even states this was done ("globals.css trimmed (1090→279 lines)").
- **Issue:** `globals.css` is **1089 lines** and still contains the full `.hero-minimal` block (lines 226–end) and all other landing-specific animation/layout styles. `landing.css` was created as a new file (823 lines) but the source was not removed from `globals.css`. Dashboard pages continue to load all landing CSS on every render — the performance win was not realized.
- **Fix:** Remove the landing-specific CSS from `globals.css` (everything from line 221 onward: `.hero-minimal*`, `.price-ticker*`, `.landing-*`, etc.) and confirm they exist only in `landing.css`. Verify `landing.css` is imported only in `src/app/landing/page.tsx`. After removal, `globals.css` should be approximately 220 lines (theme tokens + keyframes only).

---

### 2. `use-price.ts` — `selectPrice(symbol)` creates a new selector function on every render

- **File:** `Frontend/src/hooks/use-price.ts:32`
- **Rule violated:** Performance standard — selective Zustand subscriptions (`usePrice`) are supposed to only re-render when the specific symbol's price changes. The CLAUDE.md (hooks) explicitly documents: "Selective subscriptions: `useWebSocketStore(selectPrice(symbol))` only re-renders when that specific symbol's price changes."
- **Issue:** `selectPrice` is a curried function: `(symbol) => (state) => state.prices[symbol]`. Calling it inline as `useWebSocketStore(selectPrice(symbol))` creates a **new function reference on every render**. Zustand's `useStore` compares the selector by reference — when the reference changes every render, Zustand cannot use referential equality to skip the subscription check. The task description claimed "memoized curried selector with useMemo" was applied, but the actual file has no `useMemo`.
- **Fix:**
  ```ts
  import { useEffect, useRef, useMemo } from "react";
  // ...
  export function usePrice(symbol: string): UsePriceResult {
    const selector = useMemo(() => selectPrice(symbol), [symbol]);
    const entry = useWebSocketStore(selector);
    // ... rest unchanged
  }
  ```

---

### 3. `market-table-row.tsx` — `React.memo` wrapper is missing from the exported `PriceFlashCell`

- **File:** `Frontend/src/components/market/market-table-row.tsx`
- **Rule violated:** Performance standard from both `Frontend/CLAUDE.md` and `Frontend/src/components/market/CLAUDE.md`: "React.memo on table row components", "market-table-row.tsx uses React.memo to prevent re-render on unrelated price changes", "React.memo on market-table-row.tsx is critical — ensure comparison function is correct".
- **Issue:** The current `market-table-row.tsx` exports `PriceFlashCell` as a plain function with no `React.memo` wrapper at all. There is no custom comparator. The test file (line 180–228) tests memoization behavior and even has a comment saying "The custom comparator ignores children and only compares price + className" — but the implementation does not have `React.memo`. The tests for memoization will produce false positives or misleading results because they are testing a behavior that doesn't exist in the component.
- **Fix:** Wrap the export with `React.memo` and a custom comparator:
  ```tsx
  import { memo } from "react";
  // ...
  const PriceFlashCellBase = function PriceFlashCell({ price, className, children }: PriceFlashCellProps) {
    // ... implementation unchanged
  };

  export const PriceFlashCell = memo(
    PriceFlashCellBase,
    (prev, next) => prev.price === next.price && prev.className === next.className
  );
  ```

---

### 4. `battles/loading.tsx` — uses `export default` (violates no-default-exports convention)

- **File:** `Frontend/src/app/(dashboard)/battles/loading.tsx:3`
- **Rule violated:** `Frontend/CLAUDE.md` and `Frontend/src/components/CLAUDE.md` both state: "Single named export per file (no default exports)".
- **Issue:** `export default function BattlesLoading()` uses a default export. All components must use named exports.
- **Exception note:** Next.js `loading.tsx` files are a **special case** — Next.js App Router requires `loading.tsx` to use a default export. This is an intentional framework requirement, not a convention violation. The rule "no default exports" applies to component files, but Next.js special files (`page.tsx`, `layout.tsx`, `loading.tsx`, `error.tsx`) are required by the framework to use default exports. This issue is **not a real violation** — it is a false alarm. Disregard this finding.

---

### 5. `use-websocket.ts` — task description claimed `PriceBatchBuffer` was switched to `requestAnimationFrame` with Map dedup, but the actual implementation still uses `setTimeout` with a plain object

- **File:** `Frontend/src/hooks/use-websocket.ts`
- **Rule violated:** The task description for Phase 3 stated: "PriceBatchBuffer switched to rAF with Map dedup". The `development/context.md` entry also records this. However, the actual file still uses `setTimeout(..., 100)` (line 66) and `private batch: Record<string, string> = {}` (line 36) — not `requestAnimationFrame` and not a `Map`.
- **Issue:** This is a discrepancy between the stated change and what was actually committed. The existing `setTimeout` approach is documented in `Frontend/src/hooks/CLAUDE.md` as intentional ("uses `setTimeout`, not `requestAnimationFrame`. The 100ms interval is deliberate to throttle high-frequency updates"). If the rAF switch was intended, it was not applied. If the decision was reverted, the task description and context.md entry are misleading.
- **Fix (if rAF was intended):**
  ```ts
  class PriceBatchBuffer {
    private batch: Map<string, string> = new Map();
    private rafHandle: number | null = null;
    private dirty = false;

    addOne(symbol: string, price: string): void {
      this.batch.set(symbol, price);
      this.dirty = true;
      this.scheduleFlush();
    }

    addMany(prices: Record<string, string>): void {
      for (const symbol in prices) {
        this.batch.set(symbol, prices[symbol]);
      }
      this.dirty = true;
      this.scheduleFlush();
    }

    destroy(): void {
      if (this.rafHandle !== null) {
        cancelAnimationFrame(this.rafHandle);
        this.rafHandle = null;
      }
    }

    private scheduleFlush(): void {
      if (this.rafHandle !== null) return;
      this.rafHandle = requestAnimationFrame(() => {
        this.rafHandle = null;
        if (!this.dirty) return;
        const record: Record<string, string> = {};
        this.batch.forEach((price, sym) => { record[sym] = price; });
        useWebSocketStore.getState().updateAllPrices(record);
        this.batch.clear();
        this.dirty = false;
      });
    }
  }
  ```
  **If the revert to `setTimeout` was intentional** (given the CLAUDE.md note that 100ms is deliberate), update `development/context.md` and the task description to reflect the actual state. Do not leave a discrepancy between "what we said we did" and "what's in the code".

---

### 6. Phase 2 — Dashboard page lazy-loading and SectionErrorBoundary wrappers not present in `dashboard/page.tsx`

- **File:** `Frontend/src/app/(dashboard)/dashboard/page.tsx`
- **Rule violated:** Task description states "8 below-fold components lazy-loaded via next/dynamic + SectionErrorBoundary wrappers" were added. This is a documented performance improvement that was apparently committed.
- **Issue:** The actual `dashboard/page.tsx` has **no `dynamic` imports, no `Suspense`, and no `SectionErrorBoundary` wrappers**. All 12 dashboard components are still imported statically at the top. `SectionErrorBoundary` exists as a file (`section-error-boundary.tsx`) but has zero usages anywhere in the codebase (confirmed by grep). The lazy-loading and error-boundary work from Phase 2 is either not in the current file, was committed to a different branch, or was described but never applied.
- **Fix:** Confirm whether this work needs to be applied. If yes, add `dynamic` imports for below-fold components and wrap each in `SectionErrorBoundary`. If the decision was to defer this, update `development/context.md` accordingly.

---

### 7. Phase 2 — `layout.tsx` — Suspense boundaries for Header/Sidebar not present

- **File:** `Frontend/src/app/(dashboard)/layout.tsx`
- **Rule violated:** Task description states "Suspense boundaries for Header/Sidebar" were added.
- **Issue:** The dashboard layout has no `Suspense` boundaries. `Header` and `AppSidebar` are imported synchronously. This is consistent with their current non-async nature, but the stated Phase 2 work is absent.
- **Fix:** Same as above — verify whether this was intended and update either the code or the context.md to accurately reflect what was done.

---

## Warnings (should fix)

### W1. `use-price.ts` — direction computation mutates refs during render (side-effect in render body)

- **File:** `Frontend/src/hooks/use-price.ts:40-44`
- **Issue:** Lines 41-44 mutate `prevPriceRef.current` and `lastPriceRef.current` directly in the render body (not inside a `useEffect` or event handler). Mutating refs during render is generally safe in React because refs are not reactive, but it makes the code harder to reason about. In Strict Mode (dev), components render twice — this could cause `prevPriceRef` to be set to the same value twice on the first render. Not a correctness bug in production, but fragile.
- **Fix:** The pattern is acceptable given the intentional design (ref mutation for direction tracking without state). No change required, but add a comment clarifying why the ref mutation happens in the render body and that it is Strict Mode safe.

### W2. `api-client.ts` — `MAX_RETRIES = 3` but `lib/CLAUDE.md` documents only 1 retry

- **File:** `Frontend/src/lib/api-client.ts:85` and `Frontend/src/lib/CLAUDE.md`
- **Issue:** The CLAUDE.md "Gotchas" section says "Only 1 retry on 5xx (`MAX_RETRIES = 1`), with a flat 1s delay (not exponential)." The actual code now sets `MAX_RETRIES = 3` with exponential backoff (200ms, 400ms, 800ms). The implementation is correct per the task description, but the CLAUDE.md is stale and says the opposite. Anyone reading the CLAUDE.md will be confused.
- **Fix:** Update `Frontend/src/lib/CLAUDE.md` to document the current behavior: 3 retries, exponential backoff (200ms × 2^(attempt-1)).

### W3. `section-error-boundary.tsx` — `SectionErrorBoundary` is unused; exported type uses wrong syntax

- **File:** `Frontend/src/components/shared/section-error-boundary.tsx:134`
- **Issue (unused):** `SectionErrorBoundary` has zero import sites in the codebase. It was created but never wired up (related to Critical Issue #6 above). While the component itself is well-written, an unused export adds dead code.
- **Issue (type export):** Line 134 uses `export type { SectionErrorBoundaryProps }` which is correct TypeScript. However, `SectionErrorBoundaryState` is defined as an `interface` but never exported. If callers need to extend the boundary, they cannot access the state type. Minor omission.

### W4. `prefetch.ts` — query keys may drift from hook factories

- **File:** `Frontend/src/lib/prefetch.ts:74-98`
- **Issue:** The prefetch functions manually construct query keys as string literals (e.g. `["agents", "overview"]`, `["account", "positions", agentId]`). These must stay in sync with the key factories in the respective hooks. If someone renames a query key in `use-agents.ts` or `use-account.ts`, the prefetch will warm the wrong cache entry and the page will still show a loading flash. The CLAUDE.md for `lib/` acknowledges this ("Query keys must stay in sync...") but this is a fragile pattern that should be addressed.
- **Fix (preferred):** Import and use the key factory functions directly in `prefetch.ts`:
  ```ts
  import { agentKeys } from "@/hooks/use-agents";
  import { accountKeys } from "@/hooks/use-account";
  // ...
  queryKey: agentKeys.overview(),
  queryKey: accountKeys.positions(agentId),
  ```

### W5. `globals.css` — `.hero-minimal` styles use hardcoded pixel values in some places

- **File:** `Frontend/src/styles/landing.css:102`, `globals.css:297` (same content appears in both)
- **Issue:** `.hero-minimal__cta-primary:hover` includes `box-shadow: 0 0 24px rgba(240, 185, 11, 0.35)` — this is a hardcoded hex color (`#F0B90B` as rgba). This would break if the accent color token changes. The convention mandates "never hardcode hex colors — always use semantic tokens".
- **Fix:** Replace with `box-shadow: 0 0 24px color-mix(in srgb, var(--accent) 35%, transparent)`.

### W6. `use-websocket.ts` CLAUDE.md says `PriceBatchBuffer` uses `setTimeout` — still accurate if rAF switch was not applied

- **File:** `Frontend/src/hooks/CLAUDE.md`
- **Issue:** If the decision was to keep `setTimeout` (not switch to rAF), the existing CLAUDE.md note is correct and accurate. But `development/context.md` claims the rAF switch was done (see Phase 3 entry). At minimum one source is wrong.
- **Fix:** Reconcile: either apply the rAF change (see Critical Issue #5) or update `context.md`.

---

## Suggestions (consider)

### S1. `api-client.test.ts` — tests for retry logic use `vi.resetModules()` which is slow

The deduplication tests use `vi.resetModules()` + dynamic re-import to get a fresh module state. This is the correct approach for testing module-level `Map` state, but it significantly slows the test suite. Consider refactoring `inFlightRequests` to be injectable (a parameter or a resettable factory) to avoid module resets in tests.

### S2. `section-error-boundary.tsx` — `key` on a `<div>` wrapper is non-standard React pattern

`render()` returns `<div key={retryKey}>{children}</div>`. Using `key` on the root element of a class component's render output works but is an unusual pattern. The `key` on the outer `div` forces React to unmount/remount the subtree — this is the stated intention, and it works correctly. Consider extracting the children wrapper into a separate stateless component with `key` as a prop to make the intent more explicit and avoid the `key` on the render root:

```tsx
function BoundaryContent({ children, retryKey }: { children: ReactNode; retryKey: number }) {
  return <>{children}</>;
}
// In render:
return <BoundaryContent key={retryKey}>{children}</BoundaryContent>;
```

### S3. `use-market-data.ts` — `useDailyCandlesBatch` fires one query per symbol with no grouping

`useDailyCandlesBatch` (lines 207-237) uses `useQueries` to fire one `getCandles` request per symbol. For 600 symbols, this fires 600 parallel requests. Consider grouping symbols into batches of 50 (as the task description stated) or capping to only the visible virtual-scroll window. The task description mentions "batched daily candles (groups of 50)" but the actual implementation does not batch — it fires one query per symbol.

### S4. `PriceFlashCell` test for memoization (item 11) has a misleading test name

`price-flash-cell.test.tsx:202`: the test asserts `container.firstChild === firstChild` (same DOM node). This tests DOM identity but since `React.memo` is not currently in the component (Critical Issue #3), this test either passes for the wrong reason or fails silently. Fix Critical Issue #3 first, then verify this test actually validates memo behavior.

### S5. `battles/loading.tsx` — skeleton is functional but minimal

The loading skeleton shows a header + a "coming soon" placeholder, which is appropriate given the battles page has no content yet. Once battles UI is built, update this skeleton to match the real page layout (as recommended by `src/app/CLAUDE.md`: "Skeleton layout matching the real page structure").

---

## Passed Checks

- **Naming conventions:** All new files follow `kebab-case.tsx`/`.ts` (e.g., `section-error-boundary.tsx`, `prefetch.ts`, `landing.css`). All components use `PascalCase` exports. Hooks use `use-` prefix.
- **TypeScript strictness:** No `any` types observed in the reviewed files. All functions have explicit return types or inferred types from Pydantic-equivalent Zod/generic constraints. `unknown` used where appropriate.
- **`"use client"` directives:** Correctly applied — `market-table-row.tsx`, `header.tsx`, `sidebar.tsx`, `section-error-boundary.tsx` all have `"use client"`. `loading.tsx` (server component) correctly omits it.
- **Design tokens:** All reviewed components use semantic tokens (`text-profit`, `text-loss`, `text-accent`, `border-border`, `bg-card`, `bg-loss/10`, etc.). No hardcoded hex colors in component JSX (only CSS files, addressed in W5).
- **`font-mono tabular-nums`:** `chart.tsx` tooltip correctly uses `font-mono font-medium ... tabular-nums` on financial values (line 256).
- **`cn()` usage:** All components correctly use `cn()` from `@/lib/utils` for conditional class merging.
- **No cross-feature imports:** No violations detected — `shared/` components do not import from feature dirs; layout components use only `@/hooks/`, `@/stores/`, `@/lib/`.
- **State management layers:** Zustand used for WebSocket streaming data only (`use-portfolio.ts`, `use-price.ts`, `use-websocket.ts`); TanStack Query used for REST data (`use-market-data.ts`). No mixing.
- **Agent scoping in prefetch.ts:** `agentId` is correctly threaded into agent-scoped query keys in `prefetchDashboard`.
- **Dual-source price pattern:** Not modified in this changeset — confirmed preserved in the existing hook infrastructure.
- **API client deduplication logic:** The `inFlightRequests` Map implementation is correct. `promise.finally()` correctly removes the entry on both resolve and reject. POST/PUT/DELETE correctly bypass deduplication.
- **Exponential backoff:** `200 * Math.pow(2, attempt - 1)` correctly produces 200ms → 400ms → 800ms for attempts 1/2/3.
- **`SectionErrorBoundary` implementation quality:** Well-structured class component. `getDerivedStateFromError` is static. `retryKey` pattern for full subtree remount is correct. `onError` callback for telemetry is present. Dev-mode console logging is gated on `process.env.NODE_ENV`.
- **`prefetch.ts` auth gate:** `isAuthenticated()` correctly checks both JWT and API key before firing agent-scoped prefetch queries.
- **`sidebar.tsx` prefetch dedup:** `prefetchedRoutes` Set correctly prevents repeated prefetch on hover. `useCallback` with stable `[queryClient, agentId]` deps is correct.
- **Test patterns:** Tests use `vi.useFakeTimers()` / `vi.useRealTimers()` correctly for timer-based assertions. `act()` wrapping of state-triggering rerenders is correct. Response factory pattern (`okResponseFactory`) solves the "body already read" problem correctly.
- **`@/` path alias:** All imports correctly use the `@/` alias. No relative `../..` imports.

---

## Summary

The changes across Phases 1-3 show good intent and several strong implementations (GET deduplication in `api-client.ts`, `SectionErrorBoundary` design, `prefetch.ts`, sidebar activity dots, `battles/loading.tsx`). However, there are **6 critical discrepancies** between what the task description claims was done and what is actually present in the code:

1. `globals.css` still contains all the landing CSS (1089 lines, not 279)
2. `React.memo` is missing from `PriceFlashCell` — the marquee Phase 1 change is not there
3. `use-price.ts` useMemo for the curried selector is missing
4. `PriceBatchBuffer` still uses `setTimeout`, not `requestAnimationFrame`
5. Dashboard page has no dynamic imports or `SectionErrorBoundary` wrappers
6. Dashboard layout has no `Suspense` boundaries

Issues 2, 3, 5, and 6 together mean that the most impactful performance changes (memo'd market rows, selective Zustand subscriptions, lazy-loaded dashboard sections) were described but not committed. Items 1 and 4 are partial implementations where the new file exists but the old code was not updated/removed.
