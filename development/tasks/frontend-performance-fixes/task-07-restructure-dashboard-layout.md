---
task_id: 7
title: "Restructure dashboard layout to prevent full-tree re-renders"
agent: "frontend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
files:
  - "Frontend/src/app/(dashboard)/layout.tsx"
  - "Frontend/src/components/layout/header.tsx"
  - "Frontend/src/components/layout/sidebar.tsx"
---

# Task 7: Restructure Dashboard Layout to Prevent Full-Tree Re-Renders

## Assigned Agent: `frontend-developer`

## Objective

Refactor the dashboard layout so that WebSocket status changes, notification updates, and sidebar query re-fetches do NOT cause the entire page content (`{children}`) to re-render.

## Context

The current layout structure wraps everything in `<WebSocketProvider>` → `<SidebarProvider>` → content. When WS reconnects or status changes, the entire tree re-renders. Header subscribes to 3 Zustand stores; Sidebar runs 2 query hooks that re-fire on every route change.

From the performance review (C1): "Dashboard layout re-renders entire tree on WS status change — every ping."

## Files to Modify

- `Frontend/src/app/(dashboard)/layout.tsx`:
  - Add `<Suspense>` boundaries between Header, Sidebar, and `{children}`
  - Consider wrapping `{children}` in `React.memo` or using a composition pattern to isolate it from provider re-renders

- `Frontend/src/components/layout/header.tsx`:
  - Extract WS connection status indicator into its own `React.memo`'d component (`WsStatusBadge`)
  - Extract notification bell into its own `React.memo`'d component (`NotificationBell`)
  - The outer Header shell should be a server component or minimal client component that doesn't subscribe to stores directly

- `Frontend/src/components/layout/sidebar.tsx`:
  - Move `useHasTestingStrategy()` and `useHasActiveTraining()` into their own tiny `React.memo`'d indicator components
  - These indicators should be the only things that re-render when strategies/training data changes
  - Increase `staleTime` for these sidebar queries to 60-120s (they're just badge indicators)

## Acceptance Criteria

- [ ] Navigating between dashboard routes does NOT cause Header to re-render (verify with React DevTools Profiler)
- [ ] WS reconnection does NOT cause `{children}` to re-render
- [ ] Sidebar strategy/training badges still update correctly but don't trigger full sidebar re-renders
- [ ] Suspense boundaries show loading fallbacks for Header and Sidebar independently
- [ ] All existing functionality preserved (dropdowns, navigation, notifications)
- [ ] No TypeScript errors
- [ ] `pnpm build` passes

## Agent Instructions

1. Read `Frontend/CLAUDE.md` for component conventions
2. Read the three target files fully before making changes
3. Use the "islands" pattern: keep the layout shell as simple as possible, push store subscriptions down into small leaf components
4. Pattern to follow: Instead of `<Header />` subscribing to 3 stores, make `<Header>` a thin shell containing `<WsStatusBadge />`, `<NotificationBell />`, `<UserMenu />` — each subscribing to only what it needs
5. For Suspense boundaries, use the existing loading skeleton patterns from the project
6. Test route navigation and WS reconnection scenarios

## Estimated Complexity

High — architectural refactor touching 3 interconnected layout components
