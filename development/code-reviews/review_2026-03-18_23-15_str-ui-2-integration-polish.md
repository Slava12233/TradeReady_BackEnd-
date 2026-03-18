# Code Review Report

- **Date:** 2026-03-18 23:15
- **Reviewer:** code-reviewer agent
- **Verdict:** PASS WITH WARNINGS

## Files Reviewed

- `Frontend/src/components/dashboard/strategy-status-card.tsx`
- `Frontend/src/components/dashboard/training-status-card.tsx`
- `Frontend/src/app/(dashboard)/strategies/error.tsx`
- `Frontend/src/app/(dashboard)/training/error.tsx`
- `Frontend/src/app/(dashboard)/dashboard/page.tsx`
- `Frontend/src/components/layout/sidebar.tsx`
- `Frontend/src/components/shared/empty-state.tsx`
- `Frontend/src/components/strategies/strategies-page.tsx`
- `Frontend/src/components/training/training-page.tsx`
- `Frontend/src/components/strategies/version-comparison.tsx`
- `Frontend/src/components/backtest/list/backtest-list-filters.tsx`
- `Frontend/src/components/backtest/list/backtest-list-page.tsx`

## CLAUDE.md Files Consulted

- `Frontend/CLAUDE.md`
- `Frontend/src/app/CLAUDE.md`
- `Frontend/src/components/CLAUDE.md`
- `Frontend/src/components/dashboard/CLAUDE.md`
- `Frontend/src/components/shared/CLAUDE.md`
- `Frontend/src/components/layout/CLAUDE.md`
- `Frontend/src/components/strategies/CLAUDE.md`
- `Frontend/src/components/training/CLAUDE.md`
- `Frontend/src/components/backtest/CLAUDE.md`
- `Frontend/src/hooks/CLAUDE.md`
- `Frontend/src/lib/CLAUDE.md`

## Critical Issues

None.

## Warnings

### 1. `ActivityDot` ping animation missing `relative` on wrapper

- **File:** `Frontend/src/components/layout/sidebar.tsx:58`
- **Rule violated:** Tailwind animation correctness / visual correctness
- **Issue:** The standard Tailwind `animate-ping` pattern requires the wrapper element to be `position: relative` so the `absolute` inner span is positioned within the dot's 8x8px slot. The outer `<span>` currently has `flex h-2 w-2 shrink-0` but omits `relative`. Without it, the `absolute` ping ring escapes the dot slot and positions relative to the nearest positioned ancestor in the sidebar tree (likely the `SidebarMenuButton`), causing the ring to render at the wrong offset.
- **Fix:**
  ```tsx
  <span className="relative ml-auto flex h-2 w-2 shrink-0">
    <span className="animate-ping absolute inline-flex h-2 w-2 rounded-full bg-accent opacity-75" />
    <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
  </span>
  ```

### 2. Unused imports in `strategies-page.tsx`

- **File:** `Frontend/src/components/strategies/strategies-page.tsx:5-6`
- **Rule violated:** Clean code / no dead imports (ruff/tsc will flag these)
- **Issue:** `Brain`, `Plus` (from lucide-react), and `Button` (from `@/components/ui/button`) are imported but never referenced in the component. These appear to be leftover from a planned "create strategy" button that was deferred.
- **Fix:** Remove the three unused imports:
  ```tsx
  // Before
  import { Brain, Plus, Filter } from "lucide-react";
  import { Button } from "@/components/ui/button";

  // After
  import { Filter } from "lucide-react";
  // (remove the Button import entirely)
  ```

### 3. Hardcoded `blue-400` / `blue-500` color tokens in `training-status-card.tsx`

- **File:** `Frontend/src/components/dashboard/training-status-card.tsx:74,80,95`
- **Rule violated:** Frontend design token rule — never hardcode colors; use semantic tokens so dark/light mode both work
- **Issue:** Three places use raw Tailwind `blue-400`/`blue-500` color utilities instead of design tokens:
  - Line 74: `bg-blue-500/10` and `text-blue-400` on the icon wrapper
  - Line 80: `text-blue-400` and `bg-blue-500/10` on the "Running" badge
  - Line 95: `bg-blue-400` on the progress bar fill

  The project's `globals.css` / design token system does not define a semantic "training" or "info" color. If a light mode is added, raw `blue-400` on a light background may have insufficient contrast. The correct approach is to either (a) use the existing `text-accent` token for an activity indicator, or (b) add a dedicated `--color-info` token to `globals.css` and reference it as `text-info`/`bg-info`.

  The training skeleton in `training-page.tsx` line 77 has the same issue (`border-blue-500/30 bg-blue-500/5`).

- **Fix (option a — use accent token):**
  ```tsx
  // icon wrapper
  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent/10">
    <GraduationCap className="h-4 w-4 text-accent" />
  </div>
  // badge
  <span className="text-[10px] font-mono text-accent bg-accent/10 px-1.5 py-0.5 rounded">
  // progress bar
  <div className="h-full rounded-full bg-accent transition-all duration-500" ...
  ```
  Option (b) is preferred if training is intended to have a distinct visual identity — add `--color-info: #3B82F6` to `globals.css` and use `text-info`/`bg-info`.

### 4. `useStrategies` / `useTrainingRuns` hooks are not agent-scoped in dashboard cards

- **File:** `Frontend/src/components/dashboard/strategy-status-card.tsx:23`, `Frontend/src/components/dashboard/training-status-card.tsx:22`
- **Rule violated:** Agent scoping rule — all agent-scoped data queries must include `activeAgentId` in query keys; `Frontend/src/hooks/CLAUDE.md` states "hooks that fetch agent-specific data include `activeAgentId` in their query key"
- **Issue:** `useStrategies()` and `useTrainingRuns()` do not include `activeAgentId` in their query keys (confirmed by inspecting `use-strategies.ts` and `use-training-runs.ts`). In the current implementation this means switching agents in the agent switcher will not trigger a refetch of the deployed strategy or active training run shown on the dashboard. If strategies and training runs are per-account (not per-agent), this is fine — but the CLAUDE.md architecture treats all trading data as agent-scoped. This should be confirmed against the backend API contract.

  If strategies are account-scoped (shared across agents): no change needed, but add a code comment explaining why `activeAgentId` is intentionally excluded.
  If strategies are agent-scoped: both hooks need `activeAgentId` injected into the query key and passed as a query parameter.

- **Fix (if agent-scoped):** Follow the pattern in `use-trades.ts`:
  ```ts
  // use-strategies.ts
  import { useAgentStore } from "@/stores/agent-store";
  export function useStrategies(filters?: ...) {
    const agentId = useAgentStore((s) => s.activeAgentId);
    return useQuery({
      queryKey: strategyKeys.list({ ...filters, agentId }),
      ...
    });
  }
  ```

### 5. `error.tsx` files use default exports instead of named exports

- **File:** `Frontend/src/app/(dashboard)/strategies/error.tsx:16`, `Frontend/src/app/(dashboard)/training/error.tsx:16`
- **Rule violated:** Next.js App Router requirement — error boundary files (`error.tsx`) MUST use default exports; this is an App Router convention enforced by the framework
- **Clarification:** This is actually correct behavior for Next.js `error.tsx` files — the App Router requires a `default export` for special files (`page.tsx`, `layout.tsx`, `error.tsx`, `loading.tsx`). The root CLAUDE.md and components CLAUDE.md say "no default exports" but this applies to component files, not Next.js special route files. This is NOT a violation — it is correct. No action needed.

  (Noting this explicitly to document that the pattern is intentional and reviewers should not flag it.)

## Suggestions

### S1. `StrategyStatusCard` — status filter value mismatch with CLAUDE.md

- **File:** `Frontend/src/components/dashboard/strategy-status-card.tsx:25`
- **Issue:** The card looks for `s.status === "deployed"`. Checking `types.ts`, `StrategyStatus` is `"draft" | "testing" | "validated" | "deployed" | "archived"` — so `"deployed"` is correct. The strategy CLAUDE.md also uses `"active"` in the status table but the type says `"deployed"`. The CLAUDE.md status table is slightly out of sync with the type definition (shows `active` but code uses `deployed`). No functional impact — the type is the source of truth. Consider updating `strategies/CLAUDE.md` to reflect `"deployed"` not `"active"`.

### S2. `TrainingStatusCard` — truncated run ID as display label

- **File:** `Frontend/src/components/dashboard/training-status-card.tsx:68,84`
- **Issue:** The card displays a truncated UUID (`${run_id.slice(0, 8)}…`) as the training run label. Training runs in the backend (`TrainingRun` type) have no `name` field, so this is a reasonable fallback. A small improvement would be to show the config's strategy name if available (`activeRun.config?.strategy_name as string`), falling back to the truncated ID. Not required but would improve readability.

### S3. `backtest-list-filters.tsx` — checkbox uses raw `<input>` instead of shadcn `Checkbox`

- **File:** `Frontend/src/components/backtest/list/backtest-list-filters.tsx:111-119`
- **Issue:** The "Hide training episodes" filter uses a plain HTML `<input type="checkbox">` with a `rounded` class. The project uses shadcn/ui throughout; the `Checkbox` component from `@/components/ui/checkbox` would apply the correct theme tokens, respect dark/light mode, and be consistent with other form controls. The current implementation renders a raw browser checkbox that will not inherit the design system's focus ring style.
- **Fix:**
  ```tsx
  import { Checkbox } from "@/components/ui/checkbox";
  // ...
  <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
    <Checkbox
      checked={hideTrainingEpisodes}
      onCheckedChange={(checked) => onHideTrainingEpisodesChange(checked === true)}
      id="hide-training"
    />
    <span>Hide training episodes</span>
  </label>
  ```

### S4. `version-comparison.tsx` — `improvements` key access is untyped

- **File:** `Frontend/src/components/strategies/version-comparison.tsx:102`
- **Issue:** `improvements[m.key]` accesses the `improvements` object from `VersionComparisonResponse` using `as const` keys from `METRICS`. If `VersionComparisonResponse.improvements` is typed as `Record<string, number>`, this is fine. If it is more narrowly typed, TypeScript strict mode may flag the index access. Worth verifying the `improvements` type in `types.ts` matches the METRICS keys used here. This is a minor type-safety concern that won't cause a runtime issue.

### S5. `training-page.tsx` — `TrainingRunStatus` imported but unused

- **File:** `Frontend/src/components/training/training-page.tsx:10`
- **Issue:** `import type { TrainingRunStatus } from "@/lib/types"` is present but `TrainingRunStatus` is not referenced in the component body. The filtering uses inline string literals (`"running"`, `"completed"`, `"failed"`, `"cancelled"`). Either remove the import or use the type for the filter literals to get exhaustiveness checking.

### S6. Dashboard page uses container query (`@xl/main`) — verify layout context

- **File:** `Frontend/src/app/(dashboard)/dashboard/page.tsx:29`
- **Issue:** The new strategy/training row uses `@xl/main:grid-cols-2` — a container query referencing a `@container/main` named container. This is consistent with the other rows on the same page (lines 35, 45, 55, 65) that also use `@xl/main:*`. Confirm the parent layout defines `@container/main` so the breakpoint fires correctly. This is pre-existing in the page — just flagging that the new row follows the existing pattern correctly.

## Passed Checks

- **"use client" directive**: All components using hooks have `"use client"` at the top. Error boundary files correctly use `"use client"` (required by Next.js for error.tsx). The `empty-state.tsx` is a pure presentational component and correctly omits `"use client"`.
- **Named exports**: All new component files use named exports. Default exports appear only in Next.js special route files (`error.tsx`), which is correct per App Router requirements.
- **JSDoc with `@example`**: Present on all four new exported components (`StrategyStatusCard`, `TrainingStatusCard`, `StrategyError`, `TrainingError`).
- **Props interface + `className`**: Every new component defines a `TypeScript interface` for props and accepts an optional `className` merged via `cn()`.
- **Design tokens (partial)**: `strategy-status-card.tsx` correctly uses `text-profit`, `bg-profit/10`, `text-accent`, `text-muted-foreground`. Token violations are in `training-status-card.tsx` only (see Warning 3).
- **`font-mono tabular-nums`**: Applied correctly on financial/numeric strings in `training-status-card.tsx` (episode counts, percentage) and `version-comparison.tsx` (metric values).
- **No cross-feature imports**: Dashboard cards import from `@/components/strategies/` (one level down) which is correct — dashboard components may reference shared components or feature status badges. No lateral cross-feature imports observed.
- **ROUTES constants**: Both cards use `ROUTES.strategies`, `ROUTES.strategyDetail`, `ROUTES.training`, `ROUTES.trainingDetail` from `@/lib/constants` — all defined.
- **Error boundary pattern**: `strategies/error.tsx` and `training/error.tsx` follow the correct Next.js App Router error boundary shape (`error: Error & { digest?: string }`, `reset: () => void`), use semantic color tokens (`text-loss`, `bg-loss/5`), and match the existing pattern.
- **Empty state variant config**: New `"no-strategies"` and `"no-training-runs"` variants added to `variantConfig` in `empty-state.tsx` follow the established `Record<Variant, Config>` pattern with appropriate icons and descriptions.
- **Sidebar agent-strategy group**: `AgentStrategyNavGroup` correctly calls both `useHasTestingStrategy` and `useHasActiveTraining` using the existing hook API, and maps results to `activityMap` — cleanly composed without logic duplication.
- **Backtest filter logic**: The `isTrainingEpisode` helper and `hideTrainingEpisodes` filter in `backtest-list-page.tsx` are client-side only (no API change), correctly placed after the data fetch, and the filter state is initialized to `false` (opt-in, not opt-out) — good UX default.
- **Version comparison mobile layout**: The `sm:hidden` / `hidden sm:grid` pattern in `version-comparison.tsx` correctly hides the desktop header row on mobile and shows per-row inline labels instead. The `DeltaIndicator` helper is reused in both layouts.
- **TypeScript strict patterns**: No `any` observed. `unknown` not needed as data shapes are typed. Type narrowing used appropriately (`v != null`, `episodes_total && episodes_total > 0`).
- **`cn()` usage**: Conditional class merging via `cn()` throughout. No inline `style` objects except for the dynamic `width` on the progress bar (acceptable for a CSS custom property that cannot be expressed as a static Tailwind class).
- **Naming conventions**: All new files follow `kebab-case.tsx`. Components are `PascalCase`. No naming violations.
- **No hardcoded hex colors in new files** (except blue tokens in training card — see Warning 3).
- **`border-border` used correctly**: No `border-white/10` found in any changed file.
