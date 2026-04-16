---
type: task
board: customer-readiness-audit
tags:
  - ux
  - frontend
  - audit
date: 2026-04-15
---

# Task 05 — Frontend UX Audit

## 1. Page Accessibility Results (HTTP Checks)

All requests to `tradeready.io` receive a 307 redirect to `www.tradeready.io` (Vercel canonical redirect, ~200ms). Final destinations all resolve 200:

| URL | Final Status | Time (total, incl. redirect) |
|-----|-------------|------------------------------|
| `https://www.tradeready.io/` | 200 | 0.35s |
| `https://www.tradeready.io/landing` | 200 | 0.75s |
| `https://www.tradeready.io/dashboard` | 200 | 0.74s |
| `https://www.tradeready.io/market` | 200 | 0.83s |
| `https://www.tradeready.io/docs` | 200 | 0.20s |
| `https://www.tradeready.io/login` | 200 | 0.67s |
| `https://www.tradeready.io/register` | 200 | 0.50s |
| `https://www.tradeready.io/agents` | 200 | 0.56s |
| `https://www.tradeready.io/wallet` | 200 | 0.64s |
| `https://www.tradeready.io/analytics` | 200 | 0.65s |
| `https://www.tradeready.io/battles` | 200 | 0.71s |
| `https://www.tradeready.io/backtest` | 200 | 0.80s |
| `https://www.tradeready.io/leaderboard` | 200 | 0.80s |
| `https://www.tradeready.io/setup` | 200 | 0.66s |
| `https://www.tradeready.io/settings` | 200 | 0.69s |

**Result: All 15 tested routes return 200. The site is fully accessible.** The naked-domain 307→www redirect is the only quirk, and it is fast (<200ms).

---

## 2. Component Quality Assessment

### 2a. Coming Soon Page (`/`)

**File:** `src/components/coming-soon/coming-soon.tsx`

**Quality: GOOD**

- Has a functional waitlist form with email validation, loading state (`Loader2` spinner), success/error states, and an `ALREADY_SUBSCRIBED` handler.
- Feature grid (6 cards) with hover transitions, glass-morphism styling.
- 3-step "How It Works" section.
- Bottom CTA with smooth scroll back to form.
- Fixed header with backdrop blur and a "Preview Landing Page" link.
- Error/success messages use semantic color tokens (`text-loss`, `text-profit`).
- Footer with copyright.

**Issues found:**
- The header logo text reads "TradeReady.io" but the platform brand in the dashboard sidebar reads "AGENT X". Brand inconsistency across surfaces (see HIGH issues).
- The "Preview Landing Page" link feels like a developer artifact — a production visitor should not see a prompt to "preview" a separate page. This undermines confidence.
- No social proof (user count, trade volume, testimonials) on the coming-soon page.
- No social media links in the footer.

---

### 2b. Landing Page (`/landing`)

**Files:** `src/components/landing/` (15 components + step-animations subdirectory)

**Quality: GOOD**

The landing page is a rich, multi-section marketing page with:
- `HeroSection` — headline, email capture, code demo (via `HeroMinimal` primitive with typed code animation), bottom stats tag.
- `FeaturesGrid` — `FeaturesBento` with parallax gold glow, section heading.
- `HowItWorks` — animated 4-step flow with `step-animations/` sub-components.
- `AgentSkillsSection`, `AgentBattleSection`, `BacktestSection`, `McpSection` — each is a feature marketing section.
- `FrameworksSection` — integration logos.
- `PlatformPreview` — screenshot/interactive preview.
- `StatsBar` — platform metrics.
- `CtaSection` — bottom CTA with `HeroBackground`, email form, docs link.
- Below-fold sections use `next/dynamic` with skeleton fallbacks and `MotionReveal` (Framer Motion `whileInView`).
- Both `HeroSection` and `CtaSection` call `subscribeWaitlist()` — dual signup points.
- `ApiClientError` 409 (already subscribed) handled gracefully.
- `aria-labelledby` on sections, `aria-hidden` on decorative elements.

**Issues found:**
- `LandingHeader` and `LandingFooter` not reviewed in depth, but docs links were wired in during Phase 8 (good).
- `HeroSection` `codeDemoFooter` text references "OpenClaw" which may be an internal/placeholder name — needs brand review.
- No testimonials or social proof visible in reviewed components (possible gap).
- Landing page is at `/landing`, not `/` — a customer who finds `tradeready.io` gets a "Coming Soon" page, not the full marketing pitch. This is the most significant marketing-readiness gap (covered in HIGH issues).

---

### 2c. Dashboard (`/dashboard`)

**File:** `src/app/(dashboard)/dashboard/page.tsx`

**Quality: EXCELLENT**

- 11 independent `SectionErrorBoundary` wrappers — one failing section does not blank the page.
- 8 below-fold sections lazy-loaded via `next/dynamic` with matching skeleton fallbacks.
- `DashboardLoading` (`loading.tsx`) — detailed skeleton that mirrors real layout (portfolio card, equity chart, 4 table/pie rows, trades feed, quick stats).
- `PortfolioValueCard` — ambient glow driven by daily PnL sign (green/red), `NumberTicker` animation, dual-source (WS + REST), `Skeleton` placeholders while loading.
- `OpenPositionsTable` — live PnL recalculation from WS prices, `emptyVariant="no-positions"` passed to `DataTable`.
- `DataTable` propagates `emptyVariant` to `EmptyState` — confirmed by `DataTable` accepting `emptyVariant` and `isLoading`/`isError` props.
- Dashboard analytics section (strategy attribution, equity comparison, signal confidence, active trade monitor) — all lazy-loaded separately.

**Issues found:**
- `AgentStatusFooter` in sidebar shows hardcoded "Agent Alpha — Running" text (not dynamic). A new user with no agents, or a user whose agent is `idle`, will see stale label. **MEDIUM** issue.
- When no agent is selected, dashboard sections that depend on `activeAgentId` (`enabled: !!activeAgentId`) will show empty states without explicit guidance on what to do (select an agent). The empty states say "No data available" but don't prompt the user toward the agent switcher.
- `PortfolioValueCard` shows `Skeleton` while loading but has a null branch (`equity === null && !isLoading`) that renders nothing — no explicit "no data" message if the API returns null for a fresh account.

---

### 2d. Agent Components (`/agents`)

**Files:** `src/components/agents/`, `src/app/(dashboard)/agents/page.tsx`

**Quality: GOOD**

- `AgentGrid` — skeleton grid (4 `AgentCardSkeleton` cards) on loading, emoji empty state (`🤖`) with "Create your first agent" prompt on no data.
- `AgentCreateModal` — full form: name (required), balance, LLM model (presets + custom), framework (presets + custom), tags, color picker. Shows API key in second step with copy button and "save now" warning. Form validation via toast (`toast.error`).
- `AgentSwitcher` — dropdown showing all non-archived agents, Create + Manage actions at bottom, shows "No agent selected" when none active.
- `AgentsPage` — sort/filter controls, "Create Agent" button in header.

**Issues found:**
- `AgentGrid` empty state uses an emoji (`🤖`) which is explicitly prohibited by the project's own style guide ("no emojis"). This is a minor inconsistency but worth fixing. **LOW**
- `AgentCreateModal` form has no explanation of what an "agent" is for a first-time user — no contextual help or link to docs. **LOW**
- The `AgentStatusFooter` at the bottom of the sidebar is hardcoded to "Agent Alpha — Running" and does not reflect the actual active agent's name or status. **MEDIUM**

---

### 2e. Error Handling

**Files:** `src/components/shared/section-error-boundary.tsx`, `src/components/shared/error-boundary.tsx`, `src/app/(dashboard)/layout.tsx`

**Quality: EXCELLENT**

- `SectionErrorBoundary` — proper React class component, `retryKey` pattern forces full subtree re-mount on retry (clean TanStack Query slate), shows section name in error message, distinguishes "failed to load" from internal error text.
- Top-level `ErrorBoundary` in dashboard layout wraps all page children.
- Per-section `SectionErrorBoundary` wraps each of the 11 dashboard sections independently.
- `DataStalenessBanner` — detects stale price data via `data.stale` flag, shows "Delayed data" warning with age label (formatted as `Xs ago`, `Xm ago`, `Xh Xm ago`).
- `ConnectionStatus` in header shows WS connection state with label.

**Issues found:**
- `DataStalenessBanner` uses `border-b border-accent/30 bg-accent/10` for the stale banner — gold/amber is associated with warnings but the component does not have an `aria-live="polite"` or `role="alert"` attribute. Screen readers may miss it. **LOW**
- Auth pages (`LoginPage`) show `ApiClientError.message` directly to users. Backend error messages may contain internal details. **LOW** (likely fine since login errors are generic anyway).

---

### 2f. Layout — Sidebar & Header

**Files:** `src/components/layout/sidebar.tsx`, `src/components/layout/header.tsx`, `src/app/(dashboard)/layout.tsx`

**Quality: EXCELLENT**

- Sidebar organized into 4 semantic groups: Market, Trading, Agents & Strategy, Configuration.
- Collapsible to icon-only mode (`collapsible="icon"`).
- Activity dots on `/strategies` and `/training` nav items when background work is running.
- Route prefetching on hover (`prefetchDashboard`, `prefetchMarket`) with deduplication set.
- `SidebarRail` for resize handle.
- Skip-to-content link (`sr-only focus:not-sr-only`) — accessibility.
- Header: search shell, price ticker bar (live), WS connection status, notification bell (with empty state), user avatar dropdown (logout).
- Dashboard layout: `Suspense` with skeleton fallbacks for both sidebar and header.
- `WebSocketProvider` scoped to dashboard only — no WS connection on landing/auth.

**Issues found:**
- Sidebar brand name is "AGENT X" (`src/components/layout/sidebar.tsx` line 234). The coming-soon page says "TradeReady.io". The landing page and docs say "TradeReady". Three different brand strings across the product. **HIGH** — brand confusion for first users.
- `SearchShell` in the header searches "markets" but has no actual search handler — it's a visual shell only (no `onSubmit`, no navigation). A user who types and presses Enter will see nothing happen. **HIGH** — broken UX expectation.
- The `AgentStatusFooter` (sidebar bottom) is hardcoded to "Agent Alpha — Running" — not connected to live data. **MEDIUM**

---

### 2g. App Router Structure & Loading States

**Quality: EXCELLENT**

- 15 out of 15 dashboard pages have `loading.tsx` with detailed skeleton UI.
- Skeletons accurately mirror real page layouts (dashboard loading even has per-section skeletons at the right grid proportions).
- `(auth)` layout has no sidebar/header — clean centered card.
- `(dashboard)` layout has Suspense with skeleton fallbacks for both sidebar and header.
- Dynamic routes for `coin/[symbol]`, `backtest/[session_id]`, `battles/[id]`, `strategies/[id]`, `training/[run_id]` all verified in CLAUDE.md.
- `robots.ts` correctly disallows `/api/`, `/dashboard/`, `/wallet/`, `/settings/`.

**Issues found:**
- `sitemap.ts` includes `/`, `/login`, `/register`, `/market`, `/leaderboard` but NOT `/landing`. The full marketing landing page is not indexed. **HIGH** — SEO gap.
- Dashboard and protected routes (wallet, agents, settings) are reachable without auth redirect in code review — no middleware enforcing auth was observed in `src/app/(dashboard)/layout.tsx`. If there is no auth guard server-side, unauthenticated users will see the dashboard skeleton then get API 401 errors. **MEDIUM** — needs verification.

---

### 2h. Auth Flow

**Files:** `src/app/(auth)/login/page.tsx`, `src/app/(auth)/register/page.tsx`, `src/app/(dashboard)/setup/page.tsx`

**Quality: GOOD**

- Login — react-hook-form + Zod validation (`email`, `password` with min 8 char), icon-adorned inputs, show/hide password toggle, server error displayed in styled `loss/10` card, loading state on submit button.
- Register redirect → Setup Wizard via sessionStorage (`PENDING_REGISTRATION_KEY`).
- Setup Wizard — 6 steps: Register, Create Agent, Save API Key (gated by `agentKeySaved` checkbox), Download Skill, Configure Agent with code snippets, Verify connection.
- `WizardProgress` component tracks progress.
- Can skip optional steps.

**Issues found:**
- No "Forgot password" link on login page. **HIGH** — standard auth expectation missing.
- No password confirmation field on register (verify register page, but setup wizard starts from register). **MEDIUM** — needs separate check of register page.
- `canGoNext()` for step 1 and 2 returns `false` (form-driven advance) — this is correct but may confuse users who don't see an active "Next" button on those steps. No explainer text like "Fill in the form above to continue". **LOW**

---

## 3. UX Issues Found

### HIGH (P0) — Blocks customer confidence or critical journeys

| # | Location | Issue |
|---|----------|-------|
| H1 | `/` (Coming Soon) | The **root URL serves a Coming Soon page** instead of the full marketing landing page. Customers who find `tradeready.io` via organic search, word-of-mouth, or a link get a waitlist page rather than the full feature pitch. This significantly limits conversion and discovery. |
| H2 | Sidebar branding | **Brand name inconsistency**: Coming Soon = "TradeReady.io", Sidebar = "AGENT X", Landing/Docs = "TradeReady". No unified brand identity. A customer who moves from landing → login → dashboard sees three different names. |
| H3 | Header search | **Search shell is non-functional**. The search input in the dashboard header accepts typing but has no submit handler — pressing Enter does nothing. Users expect search to navigate to results. |
| H4 | Auth flow | **No "Forgot password" link** on the login page. Standard auth expectation; absence will block users who forget credentials. |
| H5 | SEO | **`/landing` not in sitemap**. The full marketing page is not indexed by search engines, reducing organic discovery. |

### MEDIUM (P1) — Degrades UX but non-blocking

| # | Location | Issue |
|---|----------|-------|
| M1 | Sidebar footer | `AgentStatusFooter` shows hardcoded "Agent Alpha — Running" text instead of the active agent's real name and status. New or multi-agent users will see incorrect information. |
| M2 | Dashboard (no agent selected) | When no agent is selected, dashboard sections that need `activeAgentId` show generic empty states ("No data available") rather than a contextual prompt: "Select an agent above to see your dashboard." |
| M3 | Auth guard | No visible server-side auth redirect in `(dashboard)/layout.tsx`. Unauthenticated users who navigate directly to `/dashboard` may see a skeleton then API errors rather than a clean redirect to `/login`. |
| M4 | Register flow | Password confirmation field not confirmed present on register page (login page omits it — needs verify). |

### LOW (P2) — Polish issues

| # | Location | Issue |
|---|----------|-------|
| L1 | Agent grid | Empty state uses an emoji (`🤖`) in violation of the project's own no-emoji style rule. |
| L2 | `DataStalenessBanner` | Missing `role="alert"` or `aria-live` — screen readers may miss stale data notification. |
| L3 | Setup Wizard | Steps 1 and 2 have no visible "Next" button (form-driven), but no helper text explains this. |
| L4 | Coming Soon | "Preview Landing Page" link in header reads like a developer link, not a user-facing CTA. Should be renamed or removed. |
| L5 | Agent create modal | No contextual help or docs link for first-time users who don't know what an "agent" is. |
| L6 | Coming Soon footer | No social media links. |
| L7 | Auth | Login server errors display raw backend messages — usually fine but could expose internals on unexpected errors. |

---

## 4. Empty State Coverage Assessment

| Page/Component | Empty State Exists | Quality |
|----------------|-------------------|---------|
| Open Positions Table | Yes (`no-positions` via `DataTable`) | Good — icon + text |
| Active Orders Table | Yes (`no-orders` via `DataTable`) | Good |
| Recent Trades Feed | Yes (`no-trades` via `DataTable`) | Good |
| Agent Grid | Yes (custom inline) | Acceptable — emoji violates style guide |
| Agent Switcher | Yes ("No agent selected" label) | Good |
| Notification Bell | Yes (Bell icon + "No notifications yet") | Good |
| Strategies | Yes (`no-strategies` variant) | Good |
| Training Runs | Yes (`no-training-runs` variant) | Good |
| Alerts | Yes (`no-alerts` variant) | Good |
| Dashboard (no agent) | Partial — sections show generic empty states | Needs contextual CTA |
| Portfolio Value Card | Partial — `null` equity with `!isLoading` renders nothing (no empty state message) | Missing |
| Dashboard analytics sections | Deferred to API response — sections show empty via `SectionErrorBoundary` if error | Good for errors, unclear for zero-data |

**Coverage summary:** 10/12 surfaces have explicit empty states. Two gaps: `PortfolioValueCard` null branch and the "no agent selected" cross-page context.

---

## 5. Error Handling Coverage

| Mechanism | Coverage |
|-----------|----------|
| `SectionErrorBoundary` (11 sections) | Excellent — per-section, retry button, re-mounts subtree |
| Top-level `ErrorBoundary` in dashboard layout | Excellent |
| `DataStalenessBanner` | Excellent — surfaces data staleness |
| `ConnectionStatus` indicator in header | Excellent — shows WS state |
| Login form — validation errors | Excellent — Zod + inline field errors |
| Login form — server errors | Good — styled error card |
| API client retries (3x exponential) | Excellent — transparent to UI |
| `ApiClientError` typed errors | Good — caught in most forms |
| TanStack Query `isError` flag | Good — passed to `DataTable` via `isError` prop |
| `DataStalenessBanner` `aria-live` | Missing |
| `PortfolioValueCard` null equity branch | Missing explicit fallback |

---

## 6. First-Impression Narrative

> "If I were a new customer discovering TradeReady.io for the first time..."

I land at `tradeready.io`. I see a "Coming Soon" page. It's clean and professional — animated ping badge, a waitlist form, a 6-feature grid, and a "How It Works" section. But I'm not getting the full product pitch yet, and I notice a small "Preview Landing Page →" link in the top right that makes me feel like I found an incomplete version.

I click through to the landing page. Now I see the real pitch — a hero with a live code demo animation, sections covering backtesting, agent battles, MCP integration, supported frameworks. This is compelling. I want to try it.

I register. The form is clean — email/password, real-time validation, password toggle. After registration I'm dropped into a 6-step "Agent Setup Wizard". This is well-structured. I go through: register → create agent → save API key (with copy button) → download skill.md → configure → verify. The wizard correctly locks the "Next" button until I acknowledge saving my API key.

I reach the dashboard. First load is seamless — detailed skeleton placeholders appear instantly while data fetches. The sidebar has "AGENT X" as the brand (I thought this was "TradeReady"?). I see "Agent Alpha — Running" in the sidebar footer even though my agent is named "MyBot" and has status "idle". Something is wrong.

The dashboard fills in. The portfolio value card glows green (good day!) with animated number counting up. The equity chart renders. Tables show empty states with clear messages. So far, good.

I click the search bar in the header and type "BTC" to find the market. Nothing happens. Enter does nothing. I give up and click "Market" in the sidebar instead.

Overall impression: **professional, data-rich, thoughtfully engineered** — but three friction points break the "wow" moment: the Coming Soon wall at the root URL, the broken search input, and the brand name inconsistency. A technical developer evaluating the platform will likely push past these, but a non-technical founder evaluating for their team may bounce.

---

## 7. Recommendations

### P0 — Critical, fix before customer demos

| Priority | Action |
|----------|--------|
| **P0-1** | Redirect `/` to `/landing` (or swap the pages so the full landing is the root URL and `/coming-soon` is the waitlist-only version). This is the single highest-impact UX change. |
| **P0-2** | Fix `SearchShell` in `header.tsx` — wire up actual navigation to `/market?q=<term>` on submit. At minimum, add `onKeyDown` Enter handler. |
| **P0-3** | Add "Forgot password" link to `LoginPage` (even if reset flow is not yet built — link to a "coming soon" page or email support). |
| **P0-4** | Unify brand name. Choose one: "TradeReady" or "TradeReady.io". Update sidebar (`sidebar.tsx` line 234), coming-soon header, all marketing copy. |

### P1 — High, fix before public launch

| Priority | Action |
|----------|--------|
| **P1-1** | Fix `AgentStatusFooter` — replace hardcoded "Agent Alpha — Running" with data from `useActiveAgent()` hook and reflect real status badge. |
| **P1-2** | Add contextual "no agent selected" empty state to dashboard: when `activeAgentId` is null, show a single full-page prompt ("Select or create an agent to see your dashboard") instead of 11 independent empty states. |
| **P1-3** | Add `/landing` to `sitemap.ts` so the marketing page is indexed. |
| **P1-4** | Verify server-side auth guard in `(dashboard)/layout.tsx` — confirm unauthenticated users are redirected to `/login` and not served skeleton + 401 errors. If missing, add Next.js middleware or server-side redirect. |
| **P1-5** | Add `role="alert"` and `aria-live="polite"` to `DataStalenessBanner`. |

### P2 — Polish, nice-to-have before public launch

| Priority | Action |
|----------|--------|
| **P2-1** | Replace `🤖` emoji in `AgentGrid` empty state with a `lucide-react` `Bot` icon (per project style rules). |
| **P2-2** | Add `PortfolioValueCard` explicit null/empty state — display "No portfolio data yet. Your agent hasn't traded." rather than silent nothing. |
| **P2-3** | Rename "Preview Landing Page →" link in coming-soon header to "See full platform →" or remove it. |
| **P2-4** | Add social media links to coming-soon footer. |
| **P2-5** | Add brief contextual help tooltip or docs link to `AgentCreateModal` ("What's an agent?"). |
| **P2-6** | Add helper text on Setup Wizard steps 1 and 2 where no "Next" button is visible: "Fill in the form above to continue." |

---

## 8. Summary Scorecard

| Area | Score | Notes |
|------|-------|-------|
| Live site accessibility | 5/5 | All 15 routes return 200 |
| Loading states / skeletons | 5/5 | 15/15 pages have loading.tsx, inline skeletons too |
| Error handling | 4/5 | Excellent boundaries, minor a11y gap on staleness banner |
| Empty state coverage | 4/5 | 10/12 surfaces covered, 2 gaps |
| Auth flow | 3/5 | Clean form but no forgot-password |
| Navigation / layout | 4/5 | Well-structured, but search shell broken |
| Branding / first impression | 2/5 | 3 different brand strings, Coming Soon wall at root |
| Onboarding (setup wizard) | 4/5 | Thorough 6-step wizard, minor UX friction |
| Agent management | 4/5 | Good CRUD, minor empty state and static footer |
| Dashboard quality | 5/5 | Best-in-class: error boundaries, lazy loads, live data |
| **Overall UX Readiness** | **40/50** | |

**Verdict:** The dashboard itself is production-grade and technically impressive. The primary gap is the marketing/onboarding funnel — root URL serves a holding page instead of the full pitch, brand naming is inconsistent across surfaces, and the header search input is broken. Fix these 4 P0 items and the frontend is customer-ready.
