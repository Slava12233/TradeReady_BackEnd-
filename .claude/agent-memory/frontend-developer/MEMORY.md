# Frontend Developer — Project Memory

## Stack
- Next.js 16 App Router, React 19, TypeScript (strict mode), Tailwind CSS v4, pnpm
- No `tailwind.config.ts` — Tailwind v4 configured entirely via `@theme inline` in `src/app/globals.css`
- `next.config.ts` wrapped with `createMDX()` from `fumadocs-mdx/next` — do not remove
- Path alias: `@/*` maps to `./src/*` — use for all imports

## App Structure
- `(auth)/` — login/register, no sidebar
- `(dashboard)/` — 16+ main pages with sidebar + header
- `docs/` — standalone Fumadocs documentation site (outside both groups)
- `/` — Coming Soon page (`src/components/coming-soon/coming-soon.tsx`)
- `/landing` — full marketing landing page
- The app is a **read-only monitoring UI** — users never trade manually; agents trade

## State Management (three layers, never mix)
- **Zustand** (`src/stores/`) — WebSocket streaming data, auth session, UI prefs. 6 stores total
- **TanStack Query** (`src/hooks/`) — all REST API data with caching; hooks wrap `src/lib/api-client.ts`
- **React state** — component-local UI state only
- Never duplicate server state in Zustand — TanStack Query owns REST data

## API Client (`src/lib/api-client.ts`)
- Native `fetch` wrapper; injects `X-API-Key` from `localStorage.getItem("api_key")`
- GET deduplication: concurrent identical GETs share one in-flight fetch (Map keyed by URL)
- 3x exponential retry on 5xx with 200/400/800ms backoff
- Throws typed `ApiClientError`
- All endpoints under `/api/v1/`; dev: set api_key manually via `localStorage.setItem("api_key", "...")`

## WebSocket Client (`src/lib/websocket-client.ts`)
- Singleton; connects to `WS_URL?api_key=...`; exponential backoff reconnect (1s base, 60s max)
- Heartbeat: inbound `{"type":"ping"}` → outbound `{"type":"pong"}`
- `WsMessage` union includes `WsPingMessage` (no `channel` property) — always guard with `"channel" in msg` before switching on `msg.channel`
- `PriceBatchBuffer` uses `requestAnimationFrame` flush with 100ms minimum guard and Map-based symbol dedup

## Styling Conventions
- Tailwind utility classes only — no inline styles, no CSS modules
- `cn()` from `src/lib/utils.ts` for conditional class merging
- Design tokens (never hardcode hex): `background`, `card`, `card-hover`, `foreground`, `muted`, `accent`, `profit`, `loss`
- Use `border-border` not `border-white/10` — hardcoded colors break light mode
- `font-mono` (JetBrains Mono) for prices/numbers; `font-sans` (Inter) for labels
- Financial colors: `text-profit`/`bg-profit/15` = green, `text-loss`/`bg-loss/15` = red, `text-accent` = gold CTA

## TypeScript Conventions
- Strict mode; no `any` — use `unknown` with type guards
- `interface` for component props, `type` for unions/intersections
- All shared types in `src/lib/types.ts`; colocate component-specific types with the component

## Naming
- Files: `kebab-case.tsx` (components), `kebab-case.ts` (hooks/utils)
- Components: `PascalCase`; Hooks: `use-` prefix; Stores: descriptive suffix (e.g., `websocket-store`)
- Constants: `UPPER_SNAKE_CASE`

## Performance Patterns
- Virtual scrolling for 600+ row market table — `@tanstack/react-virtual`
- `React.memo` on table row components with custom comparators (see `market-table-row.tsx`)
- Always memoize Zustand selector functions passed to `useWebSocketStore(selector)` — prevents re-subscription churn
- `next/dynamic` with skeleton fallbacks for below-fold dashboard sections — 8 sections lazy-loaded
- Dashboard header split into 4 memo'd islands: `WsStatusBadge`, `NotificationBell`, `UserAvatar`, `SearchShell`
- `keepPreviousData` (`placeholderData: keepPreviousData`) on paginated/filtered hooks
- `useDailyCandlesBatch` batches 50 symbols per query (600 symbols → 12 query entries for sparklines)
- Debounced search: 300ms
- Route prefetching on hover via `src/lib/prefetch.ts` — called from sidebar `onMouseEnter`
- Bundle analyzer: `ANALYZE=true pnpm build`

## Charts
- TradingView Lightweight Charts — candlestick/price on coin detail page only
- Recharts — all other charts (PnL curves, pie, bar, area, sparklines)
- `use-candles.ts` bypasses Zustand — calls `onCandleUpdate` callback directly so TradingView calls `series.update()` without React re-render
- Chart theme in `src/styles/chart-theme.ts`

## shadcn/ui
- 59 primitives available — add new ones with `pnpm dlx shadcn@latest add <component-name>`
- `src/components/ui/` — do not modify generated shadcn files directly unless extending

## Theme System
- Dark/Light/System toggle in settings; managed by `src/stores/ui-store.ts` (persisted)
- `ThemeSyncer` in `src/components/providers.tsx` syncs Zustand theme to `<html>` class
- SSR default is `"dark"` (hardcoded on `<html>` in `layout.tsx`, overridden on hydration)
- CSS variables for both themes in `src/app/globals.css` (`.dark` and `.light` classes)

## Error format from backend
- `{"error": {"code": "...", "message": "..."}}`
- Rate limit headers on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- [feedback_api_client_headers.md](feedback_api_client_headers.md) — Explicit X-Agent-Id in options.headers was being overwritten by auto-inject in executeRequest
- [project_dashboard_analytics.md](project_dashboard_analytics.md) — Agent performance analytics dashboard sections added (Task 35)
- [project_battle_system_ui.md](project_battle_system_ui.md) — Battle system UI complete (Task 34): types, API functions, 2 hooks, 9 components, 3 routes
- `src/components/ui/textarea.tsx` does NOT exist — use a plain `<textarea>` with Tailwind classes (see webhook-section.tsx for pattern)
