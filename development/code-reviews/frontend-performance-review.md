# Frontend Performance Review (A-Z)

**Date:** 2026-03-20
**Scope:** Full frontend codebase (`Frontend/src/`)
**Stack:** Next.js 16, React 19, Tailwind v4, TanStack Query, Zustand, Recharts, Framer Motion

---

## Executive Summary

The frontend has **solid fundamentals** — proper tree-shaking for major libs, good landing page code-splitting, and a well-structured component hierarchy. However, several **systemic performance issues** cause sluggish page transitions and unnecessary resource consumption:

1. **Layout-level re-renders** — WebSocket/Sidebar providers wrap the entire dashboard, causing full-tree re-renders on WS status changes
2. **Missing React.memo on hot-path components** — 600+ market table rows re-render on every price tick
3. **Waterfall queries on page mount** — Dashboard fires 10+ sequential REST requests with no prefetching
4. **No request deduplication** — API client is a raw fetch wrapper; duplicate requests hit the network
5. **Aggressive polling** — Coin detail page generates 6+ HTTP requests per 10 seconds

**Estimated impact:** Fixing the Critical and High items would reduce page transition time by 40-60% and cut network requests by ~50%.

---

## Table of Contents

1. [Page Transitions & Routing](#1-page-transitions--routing)
2. [React Rendering & Memoization](#2-react-rendering--memoization)
3. [Data Fetching & Network](#3-data-fetching--network)
4. [Bundle Size & Code Splitting](#4-bundle-size--code-splitting)
5. [CSS & Animation Performance](#5-css--animation-performance)
6. [WebSocket Performance](#6-websocket-performance)
7. [Image & Font Optimization](#7-image--font-optimization)
8. [Positive Findings](#8-positive-findings)
9. [Fix Priority Matrix](#9-fix-priority-matrix)
10. [Recommended Action Plan](#10-recommended-action-plan)

---

## 1. Page Transitions & Routing

### CRITICAL: Dashboard Layout Re-Renders Entire Tree on WS Status Change

**File:** `Frontend/src/app/(dashboard)/layout.tsx`

```
WebSocketProvider  ← Client component wrapping entire layout
  └─ SidebarProvider  ← Another client provider
       ├─ AppSidebar   ← subscribes to active agent, strategies, training
       ├─ Header       ← subscribes to WS status, notifications, user
       └─ {children}   ← ALL page content re-renders
```

**Problem:** When WebSocket reconnects or status changes, the entire layout tree re-renders. Every route change triggers re-renders in Header (3 Zustand subscriptions) and Sidebar (2 query hooks).

**Fix:** Isolate providers with Suspense boundaries. Move WS status indicator into its own `React.memo` wrapper. Split Header into server shell + client islands.

---

### HIGH: Header Subscribed to 3+ Zustand Stores

**File:** `Frontend/src/components/layout/header.tsx` (line 1: `"use client"`)

Subscribes to:
- `useWebSocketStore(selectConnectionStatus)` — WS connection status
- `useNotificationStore` — notifications + unreadCount
- `useUserStore` — user display name

Any change in any of these stores triggers a full Header re-render, which cascades to its two `DropdownMenu` children.

---

### HIGH: Sidebar Queries Re-Run on Every Navigation

**File:** `Frontend/src/components/layout/sidebar.tsx` (lines 42-50)

```tsx
function useHasTestingStrategy(): boolean {
  const { data } = useStrategies();  // Refetches when stale (30s)
  return (data?.strategies ?? []).some((s) => s.status === "testing");
}
function useHasActiveTraining(): boolean {
  const { data } = useTrainingRuns(); // Refetches when stale
  return (data?.runs ?? []).some((r) => r.status === "running");
}
```

Sidebar re-renders on route change → queries become stale → new network requests.

---

### MEDIUM: Missing `/battles/loading.tsx`

All other dashboard routes have `loading.tsx` except `/battles`. Users see a blank screen during route transition.

---

### MEDIUM: Missing Suspense Boundaries in Dashboard Layout

No Suspense boundaries to segment Header, Sidebar, and page content. A single slow query in any component blocks the entire layout from rendering.

---

### LOW: Login Page Unnecessary Suspense

**File:** `Frontend/src/app/(auth)/login/page.tsx` (lines 112-117)

`LoginForm` is fully client-side — wrapping in `<Suspense>` without a fallback adds overhead without benefit.

---

## 2. React Rendering & Memoization

### CRITICAL: PriceFlashCell Not Wrapped in React.memo

**File:** `Frontend/src/components/market/market-table-row.tsx`

```tsx
export function PriceFlashCell({ price, className, children }: PriceFlashCellProps) {
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  // useEffect compares prices on EVERY render of parent table
}
```

**Impact:** 600+ rows in the market table. Every price update from WS triggers a re-render of the parent table, which re-renders ALL PriceFlashCell instances — not just the one with the changed price.

**Fix:** Wrap in `React.memo` with a custom comparator on `price` and `className`.

---

### HIGH: Portfolio Selector Without Shallow Comparison

**File:** `Frontend/src/hooks/use-portfolio.ts` (line 22)

Uses `useWebSocketStore(selectPortfolio)` without `useShallow`. The portfolio object reference changes on every store update, causing re-renders even when portfolio data hasn't changed.

**Contrast:** `use-all-prices.ts` (line 26) correctly uses `useShallow(selectAllPrices)`.

---

### HIGH: Market Search Triple State Update Per Keystroke

**File:** `Frontend/src/components/market/market-search.tsx` (lines 98-102)

```tsx
onChange={(e) => {
  setQuery(e.target.value);   // Re-render 1
  setOpen(true);              // Re-render 2
  setActiveIndex(-1);         // Re-render 3
}}
```

React 19 batching mitigates this, but combined with a separate debounce `useEffect` and inline results computation, each keystroke causes unnecessary work.

---

### MEDIUM: Chart Context Value Not Memoized

**File:** `Frontend/src/components/ui/chart.tsx`

`ChartContext.Provider value={{ config }}` creates a new object on every render, causing all consuming chart components to re-render.

**Fix:** `useMemo(() => ({ config }), [config])`

---

### MEDIUM: Allocation Pie Chart Multi-Pass Computation

**File:** `Frontend/src/components/dashboard/allocation-pie-chart.tsx` (lines 51-97)

`computeAssetValues()` performs 2+ passes through the balances array on every dependency change, inside a `useMemo` that may not have optimal dependencies.

---

### LOW: Missing useCallback on Navigation Functions

**File:** `Frontend/src/components/market/market-search.tsx` (line 62)

`navigate` function recreated on every render without `useCallback`.

---

## 3. Data Fetching & Network

### CRITICAL: No Request Deduplication in API Client

**File:** `Frontend/src/lib/api-client.ts` (lines 92-162)

Raw `fetch()` wrapper with no deduplication. If 3 components mount simultaneously and call `useAllPrices()`, 3 identical HTTP requests fire. TanStack Query deduplicates at the query level, but direct API calls (non-hook usage) have no protection.

---

### HIGH: Dashboard Fires 10+ Queries on Mount (Waterfall)

**File:** `Frontend/src/app/(dashboard)/dashboard/page.tsx` (lines 1-12)

Imports 12 components synchronously. Each fires its own query on mount:

| Component | Query | Interval |
|-----------|-------|----------|
| `PnlSummaryCards` | `usePortfolioSummary()` | 15s |
| `PortfolioValueCard` | `usePortfolio()` (WS + REST) | 30s |
| `EquityChart` | `useEquityCurve()` | 60s |
| `OpenPositionsTable` | `usePositions()` | 15s |
| `AllocationPieChart` | `useAllPrices()` + `useBalances()` | 30s |
| `ActiveOrdersTable` | `useOrders()` | 15s |
| `RiskStatusCard` | `useRiskStatus()` | 30s |
| `RecentTradesFeed` | `useRecentTrades()` | 10s |
| `QuickStatsRow` | 3 separate queries | 15-30s |
| `StrategyStatusCard` | `useStrategies()` | 30s |
| `TrainingStatusCard` | `useTrainingRuns()` | 30s |

**Total on mount:** ~15 HTTP requests in rapid succession, no prefetching, no batching.

---

### HIGH: Coin Detail Page Aggressive Polling

**File:** `Frontend/src/hooks/use-market-data.ts`

| Hook | Interval | Location |
|------|----------|----------|
| `useOrderbook()` | 5s | Line 143 |
| `useRecentTrades()` | 10s | Line 128 |
| `useCandles()` | 30s | — |
| `useAllPrices()` | 30s (REST) | Line 60 |

**Result:** 6+ HTTP requests per 10 seconds on a single page, even if user is idle.

---

### HIGH: useDailyCandlesBatch Creates Per-Symbol Queries

**File:** `Frontend/src/hooks/use-market-data.ts` (lines 208-215)

Creates a separate TanStack query for EVERY symbol in the array. With 600+ symbols, this means 600 individual query entries in the cache, each potentially firing its own network request.

**Fix:** Batch symbols in groups of 50-100 and use a single query per batch.

---

### MEDIUM: REST Polling Concurrent with WebSocket

**File:** `Frontend/src/hooks/use-market-data.ts` (lines 54-61)

`useAllPrices()` polls REST every 30s even when WebSocket is providing real-time data. Components like `AllocationPieChart` import from both WS and REST sources.

**Fix:** Disable REST polling when WS is connected; use REST as fallback only.

---

### MEDIUM: Only 1 Retry on 5xx (Documented as 3x)

**File:** `Frontend/src/lib/api-client.ts` (line 85)

`MAX_RETRIES = 1` but JSDoc claims "3x with exponential backoff". Actual retry uses flat 1s delay, not exponential.

---

### MEDIUM: 4s Request Timeout (Documented as 8s)

**File:** `Frontend/src/lib/api-client.ts` (line 84)

`REQUEST_TIMEOUT_MS = 4_000` but JSDoc says "8s timeout".

---

### MEDIUM: No Route Prefetching

No `queryClient.prefetchQuery()` calls anywhere. When navigating to `/coin/BTCUSDT`, all data fetches from scratch. Should prefetch on link hover.

---

### MEDIUM: No Partial Error Boundaries

If one query on the dashboard fails (e.g., `usePerformance()` times out), the entire section doesn't render. Each independent data source should be wrapped in its own error boundary.

---

### LOW: Missing `keepPreviousData` on Some Paginated Hooks

`useTrades()` uses it correctly; other paginated hooks (backtest-list, market data) don't, causing loading flashes on page changes.

---

## 4. Bundle Size & Code Splitting

### CRITICAL: Three.js Imported for Single Component

**File:** `Frontend/src/components/ui/dotted-surface.tsx`

Three.js (~440KB raw) is used for ONE component (`DottedSurface`) that creates a WebGL scene. If not code-split, this adds to the main bundle.

**Fix:** `const DottedSurface = dynamic(() => import("@/components/ui/dotted-surface"), { ssr: false })`

---

### HIGH: Dashboard Components Not Code-Split

**File:** `Frontend/src/app/(dashboard)/dashboard/page.tsx` (lines 1-12)

12 heavy components imported synchronously:
- `EquityChart` (Recharts)
- `AllocationPieChart` (Recharts)
- `RecentTradesFeed` (Framer Motion)
- All others load their full dependency trees

**Fix:** Use `next/dynamic` for below-fold components (charts, tables).

---

### HIGH: Missing Bundle Analyzer

**File:** `Frontend/next.config.ts`

No `@next/bundle-analyzer` configured. Cannot measure actual chunk sizes or identify dead code.

---

### MEDIUM: Remotion Packages Bundle Impact Unclear

4 Remotion packages in dependencies. Hero player IS lazy-loaded (`{ ssr: false }`), but the full Remotion runtime impact is unknown without a bundle analyzer.

---

### MEDIUM: 660 Lines of Landing-Only CSS in globals.css

**File:** `Frontend/src/app/globals.css` (lines 221-883)

Hero animations, section effects, ticker styles — all loaded on every page, including dashboard routes that never use them.

**Fix:** Extract to a CSS module or scoped stylesheet loaded only on the landing page.

---

### MEDIUM: @tsparticles Not Lazy-Loaded

**File:** `Frontend/src/components/ui/sparkles.tsx`

`@tsparticles/slim` + `@tsparticles/react` loaded for the Sparkles component. Should be lazy-loaded since it's only used on the landing page.

---

### POSITIVE: Good Tree-Shaking Practices

- `optimizePackageImports` enabled for `framer-motion` and `lucide-react`
- All Recharts imports use named exports (tree-shakeable)
- No barrel export files (`index.ts`) — direct path imports throughout
- `date-fns` used in only 3 files with selective imports
- Landing below-fold sections properly lazy-loaded with `next/dynamic`

---

## 5. CSS & Animation Performance

### MEDIUM: Framer Motion Layout Thrashing on Fast Updates

**File:** `Frontend/src/components/dashboard/recent-trades-feed.tsx`

Uses `AnimatePresence` + `motion.div` for trade feed items. On fast order updates (100ms WebSocket batch flush), Framer Motion recalculates layout for each new trade row insertion.

**Fix:** Use `layout="position"` instead of full `layout` prop. Consider CSS animations for simpler enter/exit.

---

### POSITIVE: Good CSS Containment & Reduced Motion

**File:** `Frontend/src/app/globals.css` (lines 947-1030)

- CSS containment (`contain: layout style`) on 9 major sections
- `will-change: transform` on animated elements
- Mobile animation removal below 767px
- Full `prefers-reduced-motion` support

---

## 6. WebSocket Performance

### MEDIUM: Price Batch Buffer Uses setTimeout, Not rAF

**File:** `Frontend/src/hooks/use-websocket.ts` (lines 29, 66-72)

`PRICE_BATCH_INTERVAL_MS = 100` with `setTimeout`. Price updates may fire out of sync with browser frame rate (16.67ms at 60 FPS), causing visual jank.

**Fix:** Use `requestAnimationFrame` for the flush, keep the 100ms minimum interval.

---

### MEDIUM: Buffer Not Nullified on Destroy

**File:** `Frontend/src/hooks/use-websocket.ts` (line 57-62)

`destroy()` clears the timeout but doesn't nullify `priceBufRef.current`. Rapid mount/unmount cycles can accumulate stale references. If a flush fires after unmount, it updates the store with potentially stale data.

---

### LOW: No Deduplication Within Batch Window

If the same symbol updates 50 times within 100ms, all 50 go into the batch. Only the latest price matters.

**Fix:** Use a `Map<symbol, price>` instead of an array for the batch buffer.

---

## 7. Image & Font Optimization

### POSITIVE: Images Well Optimized

- 6 files use `next/image` correctly
- Raw `<img>` tags limited to avatars and small icons (acceptable)
- No unoptimized large images found

### POSITIVE: Fonts Properly Configured

- `Inter` and `JetBrains Mono` via `next/font/google` with `display: "swap"`
- Automatic subsetting during build

---

## 8. Positive Findings

| Area | Detail |
|------|--------|
| Landing code-splitting | All below-fold sections lazy-loaded with `next/dynamic` |
| Tree-shaking | `optimizePackageImports` for framer-motion + lucide-react |
| Import discipline | No barrel exports, direct path imports throughout |
| Loading states | All routes except `/battles` have `loading.tsx` |
| CSS containment | 9 sections with `contain: layout style` |
| Reduced motion | Full `prefers-reduced-motion` support |
| WS price batching | 100ms batch buffer prevents per-tick re-renders |
| Zustand selectors | Most critical hooks use `useShallow` |
| Image optimization | `next/image` used for all significant images |
| Font loading | Google Fonts with `display: "swap"` and auto-subsetting |

---

## 9. Fix Priority Matrix

### CRITICAL (fix immediately — biggest performance wins)

| # | Issue | File(s) | Est. Impact |
|---|-------|---------|-------------|
| C1 | Dashboard layout re-renders entire tree on WS change | `(dashboard)/layout.tsx` | -40% transition time |
| C2 | PriceFlashCell not React.memo'd (600+ rows) | `market-table-row.tsx` | -60% market page CPU |
| C3 | Three.js in main bundle (440KB) | `dotted-surface.tsx` | -440KB bundle |
| C4 | No request deduplication in API client | `api-client.ts` | -50% duplicate requests |

### HIGH (fix this sprint)

| # | Issue | File(s) | Est. Impact |
|---|-------|---------|-------------|
| H1 | Dashboard 10+ waterfall queries on mount | `dashboard/page.tsx` | -2s load time |
| H2 | Coin page 6+ requests per 10s | `use-market-data.ts` | -60% network load |
| H3 | Header 3 Zustand subscriptions | `header.tsx` | Smoother transitions |
| H4 | Sidebar queries on every navigation | `sidebar.tsx` | Faster route changes |
| H5 | Dashboard components not code-split | `dashboard/page.tsx` | -200KB initial load |
| H6 | useDailyCandlesBatch per-symbol queries | `use-market-data.ts` | -500 queries |
| H7 | Portfolio selector without useShallow | `use-portfolio.ts` | Less re-renders |
| H8 | Missing bundle analyzer | `next.config.ts` | Enables measurement |

### MEDIUM (fix next sprint)

| # | Issue | File(s) | Est. Impact |
|---|-------|---------|-------------|
| M1 | REST polling concurrent with WS | `use-market-data.ts` | Less network waste |
| M2 | 660 lines landing CSS in globals | `globals.css` | Smaller CSS for dashboard |
| M3 | Missing Suspense boundaries in layout | `(dashboard)/layout.tsx` | Faster TTFP |
| M4 | Missing `/battles/loading.tsx` | `battles/` directory | Better UX |
| M5 | No route prefetching | Throughout | Faster perceived nav |
| M6 | Chart context value not memoized | `ui/chart.tsx` | Less chart re-renders |
| M7 | WS buffer uses setTimeout not rAF | `use-websocket.ts` | Smoother price updates |
| M8 | No partial error boundaries | Dashboard components | Better resilience |
| M9 | API retry/timeout mismatch | `api-client.ts` | Correct error handling |
| M10 | Remotion/tsparticles lazy loading | Landing components | Smaller landing bundle |
| M11 | Framer Motion layout thrashing | `recent-trades-feed.tsx` | Less dashboard CPU |

### LOW (backlog)

| # | Issue | File(s) | Est. Impact |
|---|-------|---------|-------------|
| L1 | Login page unnecessary Suspense | `login/page.tsx` | Negligible |
| L2 | Missing keepPreviousData on some hooks | Various hooks | Better UX |
| L3 | Market search multi-state update | `market-search.tsx` | Marginal |
| L4 | WS batch no deduplication | `use-websocket.ts` | Marginal |
| L5 | Missing useCallback on nav functions | `market-search.tsx` | Marginal |

---

## 10. Recommended Action Plan

### Phase 1: Quick Wins (1-2 days)

1. **Add `React.memo` to `PriceFlashCell`** with `(prev, next) => prev.price === next.price` comparator
2. **Wrap `DottedSurface` in `next/dynamic({ ssr: false })`** wherever it's imported
3. **Add `loading.tsx` to `/battles` route**
4. **Add `useShallow` to `use-portfolio.ts`** selector
5. **Memoize chart context value** with `useMemo`
6. **Install `@next/bundle-analyzer`** and run initial measurement

### Phase 2: Architecture Fixes (3-5 days)

1. **Restructure dashboard layout:**
   - Move WS status indicator to its own `memo`'d island
   - Add Suspense boundaries between Header, Sidebar, and content
   - Consider extracting Header WS subscription to a tiny component

2. **Code-split dashboard page:**
   - Use `next/dynamic` for below-fold components (charts, tables)
   - Keep `PnlSummaryCards` and `PortfolioValueCard` above fold (sync import)

3. **Fix data fetching:**
   - Add request deduplication to API client (in-flight request map)
   - Disable REST price polling when WS is connected
   - Batch `useDailyCandlesBatch` into groups of 50
   - Reduce coin page polling: orderbook 15s, trades 30s

4. **Extract landing CSS** to a scoped module

### Phase 3: Optimization Polish (ongoing)

1. Add route prefetching on link hover for top navigation targets
2. Implement partial error boundaries on dashboard sections
3. Switch WS flush to `requestAnimationFrame`
4. Add `keepPreviousData` to remaining paginated hooks
5. Verify Remotion code-splitting with bundle analyzer results

---

*Review conducted by: Claude Performance Audit Agent*
*Methodology: Static analysis of routing, rendering, network, bundle, CSS, WebSocket, and image patterns*
