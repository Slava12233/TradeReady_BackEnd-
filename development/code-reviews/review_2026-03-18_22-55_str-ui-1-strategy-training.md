# Code Review Report

- **Date:** 2026-03-18 22:55
- **Reviewer:** code-reviewer agent
- **Verdict:** NEEDS FIXES

## Files Reviewed

### Lib / API Client
- `Frontend/src/lib/types.ts` (lines 810–973, new Strategy/Training types)
- `Frontend/src/lib/api-client.ts` (lines 668–844, new strategy + training functions)
- `Frontend/src/lib/constants.ts` (full file — ROUTES + NAV_ITEMS additions)

### Hooks
- `Frontend/src/hooks/use-strategies.ts`
- `Frontend/src/hooks/use-strategy-detail.ts`
- `Frontend/src/hooks/use-training-runs.ts`
- `Frontend/src/hooks/use-training-run-detail.ts`

### Strategy Components
- `Frontend/src/components/strategies/strategy-status-badge.tsx`
- `Frontend/src/components/strategies/strategy-list-table.tsx`
- `Frontend/src/components/strategies/strategy-detail-header.tsx`
- `Frontend/src/components/strategies/version-history.tsx`
- `Frontend/src/components/strategies/definition-viewer.tsx`
- `Frontend/src/components/strategies/test-results-summary.tsx`
- `Frontend/src/components/strategies/version-comparison.tsx`
- `Frontend/src/components/strategies/recommendations-card.tsx`
- `Frontend/src/components/strategies/strategies-page.tsx`
- `Frontend/src/components/strategies/strategy-detail-page.tsx`

### Training Components
- `Frontend/src/components/training/active-training-card.tsx`
- `Frontend/src/components/training/learning-curve-sparkline.tsx`
- `Frontend/src/components/training/completed-runs-table.tsx`
- `Frontend/src/components/training/run-header.tsx`
- `Frontend/src/components/training/run-summary-cards.tsx`
- `Frontend/src/components/training/episode-highlight-card.tsx`
- `Frontend/src/components/training/episodes-table.tsx`
- `Frontend/src/components/training/run-comparison-view.tsx`
- `Frontend/src/components/training/training-page.tsx`
- `Frontend/src/components/training/training-run-detail-page.tsx`

### Pages / Loading
- `Frontend/src/app/(dashboard)/strategies/page.tsx`
- `Frontend/src/app/(dashboard)/strategies/loading.tsx`
- `Frontend/src/app/(dashboard)/strategies/[id]/page.tsx`
- `Frontend/src/app/(dashboard)/strategies/[id]/loading.tsx`
- `Frontend/src/app/(dashboard)/training/page.tsx`
- `Frontend/src/app/(dashboard)/training/loading.tsx`
- `Frontend/src/app/(dashboard)/training/[run_id]/page.tsx`
- `Frontend/src/app/(dashboard)/training/[run_id]/loading.tsx`

### Backend Schemas (for type-alignment verification)
- `src/api/schemas/strategies.py`
- `src/api/schemas/strategy_tests.py`
- `src/api/schemas/training.py`

## CLAUDE.md Files Consulted

- `CLAUDE.md` (root)
- `Frontend/CLAUDE.md`
- `Frontend/src/hooks/CLAUDE.md`
- `Frontend/src/lib/CLAUDE.md`
- `Frontend/src/components/CLAUDE.md`
- `Frontend/src/app/CLAUDE.md`
- `development/CLAUDE.md`
- `development/context.md`
- `src/api/CLAUDE.md`
- `src/api/schemas/CLAUDE.md`

---

## Critical Issues (must fix)

### 1. Hook rules violation — `useLearningCurve` called inside a loop in `MultiRunChart`

- **File:** `Frontend/src/components/training/run-comparison-view.tsx:54-57`
- **Rule violated:** React Rules of Hooks — hooks must not be called inside loops, conditions, or nested functions.
- **Issue:** `MultiRunChart` calls `useLearningCurve` inside `runIds.map(...)`. This is a direct violation of the Rules of Hooks and will produce runtime errors when the number of runs changes between renders. The author even annotated this with `// eslint-disable-next-line react-hooks/rules-of-hooks`, which suppresses the lint warning but does not fix the underlying bug.
- **Fix:** Extract the per-run curve fetching into a separate child component (one component per run ID) that renders `null` but populates shared state via a callback or Zustand slice, OR restructure so each run's curve is fetched in the parent component using a stable set of hook calls. The simplest correct approach:

```tsx
// Replace MultiRunChart internals with a parent that owns all hook calls
function SingleRunCurveFetcher({
  runId, onData
}: { runId: string; onData: (id: string, data: LearningCurveData | undefined) => void }) {
  const { data } = useLearningCurve(runId, "roi_pct", 10);
  useEffect(() => { onData(runId, data); }, [data, runId, onData]);
  return null;
}
```

Then `MultiRunChart` renders one `<SingleRunCurveFetcher>` per run ID and manages merged chart data in component state.

---

### 2. Second import block for types in `api-client.ts` — violates module-level convention

- **File:** `Frontend/src/lib/api-client.ts:672-684`
- **Rule violated:** Standard TypeScript import ordering (stdlib → third-party → local); all imports from the same local module should be in a single block. The lib CLAUDE.md itself flags this as a known gotcha but notes it "works but may confuse linters."
- **Issue:** A second `import type { ... } from "./types"` block appears at line 672, after `export { ApiClientError }` and a line gap. This creates two separate import blocks from the same source file. While it doesn't break anything functionally, it violates the `ruff isort` ordering that the project enforces for Python and by convention for TypeScript. More critically, the existing types (e.g., `Strategy`, `StrategyDetailResponse`) are imported in this second block but some of them (`Strategy`, `StrategyDetailResponse`) were already declared in `types.ts` but are NOT in the original import block at lines 1-51 — meaning consumers of the `api-client.ts` module who auto-import will pick these up from the second block, causing confusing module resolution.
- **Fix:** Merge all `import type` statements from `./types` into the single block at the top of the file (lines 1-51). Since `api-client.ts` already exports many functions that reference Agent types via a second block (documented as a pre-existing issue), the new strategy/training types should at minimum follow the same second-block pattern already established for agents, or ideally the entire file should be consolidated.

---

### 3. `archiveStrategy` uses HTTP DELETE but returns `Strategy` — backend mismatch

- **File:** `Frontend/src/lib/api-client.ts:728-731`
- **Rule violated:** Backend schema alignment — the frontend type contract must match what the backend actually returns.
- **Issue:** `archiveStrategy` is implemented as a `DELETE` request but typed to return `Promise<Strategy>`. Looking at the backend (`src/api/routes/strategies.py`), the archive/delete endpoint typically returns the updated strategy object or a 204 No Content on true delete. If the endpoint returns 204, `response.json()` will throw because the body is empty (the same bug that was fixed in `tools.py` during STR-4). The naming is also semantically incorrect: the backend has both "archive" (status change) and "delete" (row removal) operations. The function should call `POST /strategies/{id}/archive` (soft-delete) rather than `DELETE /strategies/{id}` (hard-delete).
- **Fix:** Verify the exact backend route for archiving (`POST /api/v1/strategies/{id}/archive` vs `DELETE`). If the backend's archive is a soft-delete returning the updated object, change to POST. If it truly deletes and returns 204, change the return type to `Promise<void>`.

---

### 4. `deployStrategy`/`undeployStrategy` — backend `DeployRequest` requires `version` field but frontend sends no body

- **File:** `Frontend/src/lib/api-client.ts:747-757`
- **Rule violated:** Backend schema alignment — `DeployRequest` in `src/api/schemas/strategies.py` has `version: int = Field(..., ge=1)` as a required field.
- **Issue:** `deployStrategy` and `undeployStrategy` both call the backend with `method: "POST"` but pass no request body. The backend's `DeployRequest` schema requires a `version` integer. The deploy call will fail with a 422 Unprocessable Entity on every invocation. The `useDeployStrategy` mutation in the hook also accepts only `id: string` with no version parameter, so the caller cannot supply the missing version.
- **Fix:** Update `deployStrategy` to accept a `version: number` parameter and pass `{ version }` as the request body. Update `useUndeployStrategy`'s mutationFn signature accordingly (undeploy may not need a version). Update `StrategyDetailHeader` to pass `strategy.current_version` when calling deploy.

---

### 5. `useActiveTrainingRun` and `useTrainingRunDetail` share the same query key — will cause cache collision

- **File:** `Frontend/src/hooks/use-training-run-detail.ts:21-50`
- **Rule violated:** TanStack Query patterns — hooks with different polling behaviors that target the same data shape must use distinct cache keys to avoid overwriting each other's cache configuration (especially `staleTime`).
- **Issue:** Both `useActiveTrainingRun` (lines 20-35, `staleTime: 2_000`, polls every 2s) and `useTrainingRunDetail` (lines 42-50, `staleTime: 30_000`, no polling) share `trainingKeys.detail(runId)` as their query key. TanStack Query merges cache entries by key. When both hooks are mounted for the same `runId`, the 30s staleTime from `useTrainingRunDetail` will be overwritten by the 2s staleTime from `useActiveTrainingRun`, causing the detail view for a completed run to poll every 2s indefinitely even though `refetchInterval` would stop it. But more critically, if `useTrainingRunDetail` mounts after the run completes and `useActiveTrainingRun` has already stopped polling, the detail view will get stale data with a 2s stale window that never refetches.
- **Fix:** Use separate query keys:
  - `useActiveTrainingRun`: `["training", "active", runId]`
  - `useTrainingRunDetail`: `trainingKeys.detail(runId)` (keep the existing key for this one)

---

### 6. Hardcoded hex colors in Recharts chart components

- **File:** `Frontend/src/components/training/run-comparison-view.tsx:23-31`
- **Rule violated:** "Never hardcode hex colors — always use semantic tokens so dark/light mode both work" (Frontend CLAUDE.md and components CLAUDE.md).
- **Issue:** `CHART_COLORS` array at line 23 contains 6 hardcoded hex strings (`"#F0B90B"`, `"#0ECB81"`, `"#F6465D"`, `"#60A5FA"`, `"#A78BFA"`, `"#FB923C"`). The first three are the accent/profit/loss tokens, which means if the theme changes these values, the chart colors will desync. The latter three (blue, purple, orange) have no design token equivalents, which is a reasonable exception — but the first three should use CSS variable references (`var(--color-accent)`, etc.) to stay in sync with the theme system.
- **Fix:** Replace the first three entries with CSS variable references:
  ```ts
  const CHART_COLORS = [
    "var(--color-accent, #F0B90B)",
    "var(--color-profit, #0ECB81)",
    "var(--color-loss, #F6465D)",
    "#60A5FA",
    "#A78BFA",
    "#FB923C",
  ];
  ```
  Note: `learning-curve-sparkline.tsx` line 46 already follows this pattern correctly — `run-comparison-view.tsx` should match it.

---

## Warnings (should fix)

### W1. `strategies/page.tsx` uses `"use client"` on a Next.js App Router page

- **File:** `Frontend/src/app/(dashboard)/strategies/page.tsx:1`
- **Issue:** The page file exports a default function with `"use client"` at the top. Per the app CLAUDE.md, page files in the `(dashboard)` group can be client components if they use hooks, but the actual page content (`StrategiesPage`) already has `"use client"` and handles all the hook usage. The route page component itself only renders a wrapper div and the page component — it does not use any hooks directly. Making the page a server component and letting `StrategiesPage` be the client boundary would allow the page metadata and server-side HTML to be generated correctly.
- **Fix:** Remove `"use client"` from `page.tsx`. The `StrategiesPage` component imported inside already has `"use client"` and will trigger the client boundary at that level. Same applies to `training/page.tsx`.

### W2. `runTest` API function uses `POST /strategies/{id}/test` but backend route is likely `POST /strategies/{id}/tests`

- **File:** `Frontend/src/lib/api-client.ts:767`
- **Issue:** The function posts to `/strategies/${strategyId}/test` (singular) but the backend routes CLAUDE.md and strategy_tests schema refers to test run endpoints under `/strategies/*/tests/` (plural). This will return a 404. The `getTestRuns` function correctly uses `/strategies/${strategyId}/tests` (plural). Verify the exact backend route path.
- **Fix:** Confirm the backend route. If the start-test endpoint is `POST /strategies/{id}/tests`, change to `/strategies/${strategyId}/tests`.

### W3. `trainingKeys.comparison` uses an array as part of the query key — array referential equality will break cache matching

- **File:** `Frontend/src/hooks/use-training-runs.ts:22`
- **Issue:** `comparison: (runIds: string[]) => ["training", "compare", runIds] as const` — `runIds` is an array reference. TanStack Query uses deep equality for query key comparison, so this will work correctly at runtime (TanStack Query serializes arrays). However, this is a subtle gotcha documented in the hooks CLAUDE.md: "Query key factories must use `as const`". The `runIds` array inside `as const` is still mutable, which means TypeScript won't complain if the wrong array is passed. Better to spread it: `["training", "compare", ...runIds] as const`.
- **Fix:** `comparison: (runIds: string[]) => ["training", "compare", ...runIds] as const`

### W4. `StrategyDefinition` TypeScript type has `[key: string]: unknown` index signature causing unsafe field access

- **File:** `Frontend/src/lib/types.ts:821`
- **Issue:** `StrategyDefinition` uses `[key: string]: unknown` as an index signature alongside typed properties (`pairs`, `entry_conditions`, etc.). This means TypeScript will allow accessing any property without type errors, but also means the typed properties must be compatible with `unknown`, which forces them all to be `unknown`. The backend returns `dict[str, Any]` for this field (i.e., arbitrary JSON), so the `unknown` index is accurate, but named fields like `pairs: string[]` become unreachable via the index signature.  In `definition-viewer.tsx` the destructuring `const { pairs, entry_conditions, exit_conditions, ...rest } = definition` works because `pairs` etc. are explicitly typed, but callers accessing `definition["pairs"]` via the index signature get `unknown`. Prefer a discriminated union or remove the index signature and widen only the named fields to be optional.
- **Fix (pragmatic):** Remove the `[key: string]: unknown` index signature. If arbitrary extra fields must be accepted, model it as:
  ```ts
  export interface StrategyDefinition {
    pairs: string[];
    entry_conditions: Record<string, unknown>;
    exit_conditions: Record<string, unknown>;
    position_size_pct?: number;
    max_open_positions?: number;
  }
  ```
  The `...rest` spread in `definition-viewer.tsx` will still work since TypeScript allows it even without an index signature when the object is typed structurally.

### W5. `AggregatedMetrics` TypeScript type has `[key: string]: unknown` index signature

- **File:** `Frontend/src/lib/types.ts:893`
- **Issue:** Same pattern as W4. The index signature `[key: string]: unknown` alongside typed `number` properties (`avg_roi_pct: number`, etc.) causes TypeScript to widen all typed properties to `unknown`, defeating the purpose of having the typed fields.
- **Fix:** Remove the index signature. The dynamic key access in `run-summary-cards.tsx` (e.g., `stats["avg_roi_pct"]`) can be typed safely with a looser parent type:
  ```ts
  export interface AggregatedMetrics {
    avg_roi_pct: number;
    avg_sharpe: number;
    avg_max_drawdown_pct: number;
    total_trades: number;
    win_rate: number;
    episodes_completed: number;
    by_pair?: PairBreakdown[];
  }
  ```

### W6. `strategy-status-badge.tsx` — `"testing"` status uses `text-blue-400` (hardcoded color token)

- **File:** `Frontend/src/components/strategies/strategy-status-badge.tsx:34,48`
- **Issue:** `text-blue-400` and `bg-blue-400/10` are Tailwind color utility classes, not project design tokens. While not a hex hardcode, they will not adapt if the theme changes and they do not have a semantic counterpart (there is no `text-info` token in the project). The `active-training-card.tsx` and `run-header.tsx` also use `text-blue-400` and `bg-blue-400/10` for "running" status styling.
- **Recommendation:** This is acceptable if the project acknowledges `text-blue-400` as a consistent "info/in-progress" color convention (it appears in multiple places). If it becomes a theme concern later, a `text-info` token should be added to `globals.css`. Flag for awareness rather than immediate change.

### W7. `getLearningCurve` and `compareTrainingRuns` build query strings via string interpolation — inconsistent with `getStrategies`/`getTrainingRuns`

- **File:** `Frontend/src/lib/api-client.ts:829-843`
- **Issue:** `getLearningCurve` and `compareTrainingRuns` build their query strings via template literals (`?metric=${metric}&window=${window}`, `?run_ids=${runIds.join(",")}`). The other parameterized functions in the same file (`getStrategies`, `getTrainingRuns`) use `URLSearchParams` for proper encoding. If `metric` or `run_ids` ever contain special characters, the manual interpolation will break.
- **Fix:** Use `URLSearchParams`:
  ```ts
  export function getLearningCurve(runId: string, metric = "roi_pct", window = 10): Promise<LearningCurveData> {
    const qs = new URLSearchParams({ metric, window: String(window) });
    return request<LearningCurveData>(`/training/runs/${runId}/learning-curve?${qs}`);
  }
  ```

### W8. Backend `TrainingRunDetailResponse.episodes` is `list[dict[str, Any]]` but frontend `TrainingRunDetail.episodes` types it as `TrainingEpisode[]`

- **File:** `Frontend/src/lib/types.ts:958` vs `src/api/schemas/training.py:63`
- **Issue:** The backend serializes episodes as `list[dict[str, Any]]` — untyped dictionaries. The frontend assumes they will match `TrainingEpisode` shape. If the backend ever returns a field that doesn't match (or uses a different key name like `reward_sum` vs `reward`), the frontend code will silently fail or render wrong values. The `TrainingEpisode` type expects `reward: number` but the backend schema uses `reward_sum` in `ReportEpisodeRequest`. It's unclear if the stored field is `reward` or `reward_sum` — this should be verified against the actual DB model.
- **Fix:** Cross-check `src/database/models.py` `TrainingEpisode` model field names against the `TrainingEpisode` TypeScript interface. At minimum, add a comment documenting the field mapping.

---

## Suggestions (consider)

### S1. `strategy-detail-page.tsx` — `Plus` icon imported in `strategies-page.tsx` but never used

- **File:** `Frontend/src/components/strategies/strategies-page.tsx:5`
- `Plus` is in the lucide-react import but nothing in the file renders it (the "Create Strategy" button that would use it was not implemented). Remove the unused import to avoid TypeScript/lint warnings.

### S2. `run-comparison-view.tsx` — `RunCurveLayer` component is declared but does nothing

- **File:** `Frontend/src/components/training/run-comparison-view.tsx:47-50`
- The `RunCurveLayer` component at line 47 is a stub that returns `null` and is never used. The comment says "used for side-effects" but there are no side effects. This dead code should be removed.

### S3. `version-history.tsx` — `idx === 0` check for "latest" badge conflicts with "current" badge logic

- **File:** `Frontend/src/components/strategies/version-history.tsx:75-79`
- When `idx === 0` (most recent version) AND `v.version === currentVersion`, only "current" renders because of the `!isCurrent` condition on the "latest" badge. But when the latest version is NOT the current version, "latest" badge appears — which is correct for draft/test workflows. This is fine behavior but worth a clarifying comment.

### S4. `episodes-table.tsx` — `max-h-96 overflow-y-auto` provides virtualization for a small list, consider noting the 96-item visual limit

- **File:** `Frontend/src/components/training/episodes-table.tsx:104`
- For training runs with hundreds or thousands of episodes, `max-h-96` limits visible rows to ~12 at once with a scroll container. This is acceptable for now but if training runs grow to thousands of episodes, virtual scrolling (already used in the market table) would be needed here too.

### S5. `LearningCurveChart` shadows the built-in `window` identifier

- **File:** `Frontend/src/components/training/learning-curve-chart.tsx:72`
- `const [window, setWindow] = useState(10)` — `window` is a globally recognized browser identifier. TypeScript in strict mode won't error here since it's a local variable, but it makes code harder to read and could trip up static analysis tools. Rename to `smoothingWindow` or `smoothWindow`.

### S6. `strategy-detail-page.tsx` missing JSDoc on the exported function

- **File:** `Frontend/src/components/strategies/strategy-detail-page.tsx:35`
- The component CLAUDE.md states: "JSDoc comment with `@example` on the exported function." `StrategyDetailPage` and `TrainingRunDetailPage` are the two page wrapper components that are missing this JSDoc. Minor but consistent with project standards.

### S7. `use-strategies.ts` — `useStrategies` is not agent-scoped but strategies may be agent-owned

- **File:** `Frontend/src/hooks/use-strategies.ts:42-53`
- The hook does not include `activeAgentId` in its query key. Per the hooks CLAUDE.md: "hooks that fetch agent-specific data include `activeAgentId` in their query key so data auto-refetches on agent switch." Whether strategies are account-scoped or agent-scoped depends on the backend implementation — if strategies belong to an account (not an agent), the current behavior is correct. If they are agent-scoped, the query key is missing the agent dimension. Verify the backend ownership model and update if needed.

---

## Passed Checks

- **File naming**: All new files use `kebab-case.tsx` / `kebab-case.ts`. All component names are `PascalCase`. All hook names use `use-` prefix.
- **`"use client"` directives**: All components that use hooks, event handlers, or browser APIs have `"use client"`. Pure display-only components have it too (defensively correct for this codebase pattern).
- **Design tokens usage**: Components correctly use `text-profit`, `text-loss`, `text-muted-foreground`, `bg-card`, `border-border`, `text-accent` throughout. No raw hex values in component styling (Recharts `CHART_COLORS` exception flagged above).
- **`cn()` from `@/lib/utils`**: All conditional class merging uses `cn()`. No inline `style={{}}` for theming.
- **`font-mono tabular-nums`**: All financial numbers (rewards, ROI %, Sharpe, episode counts) consistently use `font-mono tabular-nums`. This is well-applied across all components.
- **`@/*` path alias**: All imports use `@/lib/...`, `@/components/...`, `@/hooks/...` correctly. No relative `../../` imports.
- **TanStack Query patterns**: Query key factories exported as `as const` tuples. All hooks gate on `!!getApiKey()`. Standard `staleTime`/`gcTime` values used. Mutation `onSuccess` callbacks invalidate relevant keys.
- **No `any` types**: New TypeScript interfaces use `unknown` for dynamic fields (`Record<string, unknown>` for config, `[key: string]: unknown` for index signatures). The index signature concern is noted under warnings, not as a `any` violation.
- **Single named exports**: All components use named exports, no default exports from component files. (Exception: page routes use `export default` which is required by Next.js App Router — correct.)
- **`interface` for props, `type` for unions**: Props all use `interface`. Status types use `type` unions. Correctly applied.
- **JSDoc with `@example`**: Present on all exported component functions in new files.
- **`className` prop acceptance**: All components accept and forward an optional `className` prop merged via `cn()`.
- **No cross-feature imports**: `strategies/` components import from `shared/` and `ui/` only, not from `training/` or other feature directories.
- **Loading files**: All four new pages have corresponding `loading.tsx` files with appropriate skeleton layouts. Loading files are server components (no `"use client"`).
- **Backend type alignment (broad)**: `Strategy`, `StrategyVersion`, `StrategyListResponse` TypeScript interfaces match `StrategyResponse` / `StrategyVersionResponse` / `StrategyListResponse` Pydantic schemas. `TrainingRun` matches `TrainingRunResponse`. `LearningCurveData` matches `LearningCurveResponse`. `VersionComparisonResponse` and `VersionMetrics` match the backend counterparts exactly.
- **Polling patterns**: `useTrainingRuns` correctly polls every 10s only when active runs exist. `useActiveTrainingRun` auto-stops polling on terminal status. Pattern mirrors `use-backtest-status.ts`.
- **`gcTime: 5 * 60_000`**: Consistent with project standard across all new hooks.
- **No hardcoded secrets or API keys**: None present.
- **No `border-white/10`**: Not found in any new file. `border-border` used correctly throughout.
- **Recharts code-split concern**: Recharts is imported at the module level in `learning-curve-chart.tsx`, `learning-curve-sparkline.tsx`, and `run-comparison-view.tsx`. The Frontend CLAUDE.md states "Code split heavy libs (TradingView, Recharts) — only load on pages that need them." However, checking the existing codebase, Recharts is already used without dynamic imports in analytics and backtest components — this is a pre-existing pattern. Flagged for awareness only, not introduced by this PR.
