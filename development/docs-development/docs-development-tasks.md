# Documentation Site — Task Tracker (A-Z)

<!-- last-updated: 2026-03-19 -->

> **Reference:** See `docs-development-plan.md` for full architecture, design specs, and rationale.

---

## Status Legend

- `[ ]` — Not started
- `[~]` — In progress
- `[x]` — Complete
- `[!]` — Blocked
- `[—]` — Skipped / Not applicable

---

## Phase 1: Infrastructure Setup

**Lead:** `frontend-developer`
**Support:** `code-reviewer`, `test-runner`
**Depends on:** Nothing (first phase)
**Goal:** Fumadocs installed, configured, rendering a welcome page at `/docs`.

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 1.1 | Install Fumadocs packages | `frontend-developer` | [x] | `pnpm add fumadocs-core fumadocs-ui fumadocs-mdx` + `pnpm add -D @types/mdx` |
| 1.2 | Create `Frontend/source.config.ts` | `frontend-developer` | [x] | Fumadocs content source config pointing to `content/docs/` |
| 1.3 | Update `Frontend/next.config.ts` | `frontend-developer` | [x] | Wrapped with `createMDX()` from `fumadocs-mdx/next` |
| 1.4 | Create content loader `Frontend/src/lib/source.ts` | `frontend-developer` | [x] | `loader()` from `fumadocs-core/source` using generated source |
| 1.5 | Create docs layout `Frontend/src/app/docs/layout.tsx` | `frontend-developer` | [x] | `DocsLayout` + `RootProvider` with dark theme, brand logo, nav links |
| 1.6 | Create catch-all page `Frontend/src/app/docs/[[...slug]]/page.tsx` | `frontend-developer` | [x] | MDX renderer with `generateStaticParams` + `generateMetadata` |
| 1.7 | Create welcome page `Frontend/content/docs/index.mdx` | `frontend-developer` | [x] | Platform overview, 3 delivery modes, quick links table |
| 1.8 | Create theme CSS `Frontend/src/app/docs/docs-theme.css` | `frontend-developer` | [x] | Dark navy (#0B0E11, #1E2329), gold accent (#F0B90B) |
| 1.9 | Add `RootProvider` to docs layout | `frontend-developer` | [x] | Merged into layout.tsx (task 1.5) |
| 1.10 | Verify `/docs` is public (no auth) | `frontend-developer` | [x] | Outside `(dashboard)` group. Dashboard docs moved to `/docs-hub` |
| 1.11 | Run `pnpm build` — zero errors | `test-runner` | [x] | Build passes, `/docs` route registered |
| 1.12 | Code review Phase 1 | `code-reviewer` | [—] | Deferred — reviewed inline during implementation |

**Exit criteria:** `/docs` renders welcome page with Fumadocs sidebar and search skeleton.

---

## Phase 2: Content Migration & Writing

**Lead:** `doc-updater`
**Support:** `codebase-researcher` (accuracy verification), `frontend-developer` (MDX formatting)
**Depends on:** Phase 1 complete
**Goal:** All ~45 MDX pages written, rendering correctly at `/docs/*`.

### 2A. Directory Structure & Sidebar Config

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 2A.1 | Create all section directories under `Frontend/content/docs/` | `doc-updater` | [x] | All 10 section dirs + `strategies/` and `gym/` created |
| 2A.2 | Create root `meta.json` | `doc-updater` | [x] | 4 separator groups, 12 section entries |
| 2A.3 | Create `concepts/meta.json` | `doc-updater` | [x] | Order: how-it-works, agents, trading-rules, risk-management |
| 2A.4 | Create `api/meta.json` | `doc-updater` | [x] | Order: authentication, market-data, trading, account, analytics, agents, strategies, strategy-testing, training, battles, backtesting, errors, rate-limits |
| 2A.5 | Create `websocket/meta.json` | `doc-updater` | [x] | Order: connection, channels |
| 2A.6 | Create `sdk/meta.json` | `doc-updater` | [x] | Order: installation, sync-client, async-client, websocket-client, error-handling |
| 2A.7 | Create `mcp/meta.json` | `doc-updater` | [x] | Order: overview, setup, tools |
| 2A.8 | Create `frameworks/meta.json` | `doc-updater` | [x] | Order: langchain, crewai, agent-zero, openclaw |
| 2A.9 | Create `strategies/meta.json` | `doc-updater` | [x] | Order: overview, indicators, testing, deployment |
| 2A.10 | Create `gym/meta.json` | `doc-updater` | [x] | Order: overview, environments, rewards, training-tracking, examples |
| 2A.11 | Create `backtesting/meta.json` | `doc-updater` | [x] | Order: overview, guide, strategies |
| 2A.12 | Create `battles/meta.json` | `doc-updater` | [x] | Order: overview, lifecycle, live-monitoring, results-replay |

### 2B. Welcome & Quickstart (2 pages)

| # | Task | Agent | Status | Source |
|---|------|-------|--------|--------|
| 2B.1 | Write `index.mdx` (welcome) | `frontend-developer` | [x] | Created in Phase 1 — platform overview, 3 delivery modes, quick links |
| 2B.2 | Write `quickstart.mdx` | `doc-updater` | [x] | Converted from `docs/quickstart.md` with Tabs/Callout components |

### 2C. Concepts Section (4 pages)

| # | Task | Agent | Status | Source |
|---|------|-------|--------|--------|
| 2C.1 | Write `concepts/how-it-works.mdx` | `doc-updater` | [x] | Virtual-funds-on-real-prices premise, agent flow, auth methods |
| 2C.2 | Write `concepts/agents.mdx` | `doc-updater` | [x] | Multi-agent model, wallets, lifecycle, endpoint table, Callouts |
| 2C.3 | Write `concepts/trading-rules.mdx` | `doc-updater` | [x] | Fees, slippage model, 4 order types, position sizing, decimal rules |
| 2C.4 | Write `concepts/risk-management.mdx` | `doc-updater` | [x] | 8-step validation, circuit breaker, rate limit tiers, risk profiles |

### 2D. API Section (13 pages)

| # | Task | Agent | Status | Source | Verify Against |
|---|------|-------|--------|--------|----------------|
| 2D.1 | Write `api/authentication.mdx` | `doc-updater` | [x] | 3 auth endpoints, API key vs JWT, rate limit headers |
| 2D.2 | Write `api/market-data.mdx` | `doc-updater` | [x] | 8 public endpoints, candle intervals, synthetic orderbook note |
| 2D.3 | Write `api/trading.mdx` | `doc-updater` | [x] | 7 endpoints, all 4 order types, practical workflow example |
| 2D.4 | Write `api/account.mdx` | `doc-updater` | [x] | 7 endpoints, destructive reset callout, startup sequence |
| 2D.5 | Write `api/analytics.mdx` | `doc-updater` | [x] | 3 endpoints, metric definitions table, performance patterns |
| 2D.6 | Write `api/agents.mdx` | `doc-updater` | [x] | 14 endpoints, JWT-only callout, agent auth scoping |
| 2D.7 | Write `api/strategies.mdx` **[NEW]** | `doc-updater` | [x] | 10 endpoints, full definition schema, lifecycle diagram |
| 2D.8 | Write `api/strategy-testing.mdx` **[NEW]** | `doc-updater` | [x] | 6 endpoints, 11 recommendation rules, version comparison |
| 2D.9 | Write `api/training.mdx` **[NEW]** | `doc-updater` | [x] | 7 endpoints, client-provided UUID pattern, learning curve |
| 2D.10 | Write `api/battles.mdx` | `doc-updater` | [x] | 20 endpoints, state machine, presets, historical mode |
| 2D.11 | Write `api/backtesting.mdx` | `doc-updater` | [x] | 24+ endpoints, full lifecycle, RSI example, sandbox trading |
| 2D.12 | Write `api/errors.mdx` | `doc-updater` | [x] | 18 error codes, SDK exception mapping, common mistakes |
| 2D.13 | Write `api/rate-limits.mdx` | `doc-updater` | [x] | 3 HTTP tiers, retry strategies, best practices |

### 2E. WebSocket Section (2 pages)

| # | Task | Agent | Status | Source | Verify Against |
|---|------|-------|--------|--------|----------------|
| 2E.1 | Write `websocket/connection.mdx` | `doc-updater` | [x] | Auth, heartbeat, subscription protocol, reconnection, error codes |
| 2E.2 | Write `websocket/channels.mdx` | `doc-updater` | [x] | 6 channels with subscription msgs, field tables, multi-channel example |

### 2F. SDK Section (5 pages)

| # | Task | Agent | Status | Source | Verify Against |
|---|------|-------|--------|--------|----------------|
| 2F.1 | Write `sdk/installation.mdx` | `doc-updater` | [x] | pip install, constructor params, .env setup, quick example |
| 2F.2 | Write `sdk/sync-client.mdx` | `doc-updater` | [x] | 37 methods across 7 groups, 13 response models |
| 2F.3 | Write `sdk/async-client.mdx` | `doc-updater` | [x] | Async API surface, asyncio.gather patterns, FastAPI integration |
| 2F.4 | Write `sdk/websocket-client.mdx` | `doc-updater` | [x] | 4 decorators, "all" wildcard, thread-based price cache example |
| 2F.5 | Write `sdk/error-handling.mdx` | `doc-updater` | [x] | 10 exceptions, retry table, layered catch pattern |

### 2G. MCP Section (3 pages)

| # | Task | Agent | Status | Source | Verify Against |
|---|------|-------|--------|--------|----------------|
| 2G.1 | Write `mcp/overview.mdx` | `doc-updater` | [x] | MCP architecture, 10-category summary, MCP vs SDK vs REST decision table |
| 2G.2 | Write `mcp/setup.mdx` | `doc-updater` | [x] | Claude Desktop + Cline tabs, env vars, troubleshooting |
| 2G.3 | Write `mcp/tools.mdx` | `doc-updater` | [x] | All 58 tools with param tables, 3 multi-step examples |

### 2H. Framework Guides (4 pages)

| # | Task | Agent | Status | Source |
|---|------|-------|--------|--------|
| 2H.1 | Write `frameworks/langchain.mdx` | `doc-updater` | [x] | 8-step guide, ReAct agent, StructuredTool, async agent |
| 2H.2 | Write `frameworks/crewai.mdx` | `doc-updater` | [x] | 3-agent crew, sequential tasks, hierarchical mode |
| 2H.3 | Write `frameworks/agent-zero.mdx` | `doc-updater` | [x] | Skill file placement, 8 Tool subclasses, config reference |
| 2H.4 | Write `frameworks/openclaw.mdx` | `doc-updater` | [x] | Config options, 6 tool decorators, agent.yaml reference |

### 2I. Strategy Section — NEW (4 pages)

| # | Task | Agent | Status | Source | Verify Against |
|---|------|-------|--------|--------|----------------|
| 2I.1 | Write `strategies/overview.mdx` | `doc-updater` + `codebase-researcher` | [x] | Lifecycle state machine, full JSON schema, worked example, 10 endpoints |
| 2I.2 | Write `strategies/indicators.mdx` | `doc-updater` + `codebase-researcher` | [x] | 7 indicators + volume MA, all condition keys, reference table |
| 2I.3 | Write `strategies/testing.mdx` | `doc-updater` + `codebase-researcher` | [x] | Multi-episode testing, 11 recommendation rules, iteration workflow |
| 2I.4 | Write `strategies/deployment.mdx` | `doc-updater` + `codebase-researcher` | [x] | Deploy/undeploy, executor behavior, versioning, comparison |

### 2J. Gymnasium / RL Training Section — NEW (5 pages)

| # | Task | Agent | Status | Source | Verify Against |
|---|------|-------|--------|--------|----------------|
| 2J.1 | Write `gym/overview.mdx` | `doc-updater` + `codebase-researcher` | [x] | Installation, quick start loop, 5-tuple API, 3 workflow types |
| 2J.2 | Write `gym/environments.mdx` | `doc-updater` + `codebase-researcher` | [x] | 7 envs, action spaces, observation space, 3 wrappers |
| 2J.3 | Write `gym/rewards.mdx` | `doc-updater` + `codebase-researcher` | [x] | 5 reward functions, custom reward example, comparison table |
| 2J.4 | Write `gym/training-tracking.mdx` | `doc-updater` + `codebase-researcher` | [x] | TrainingTracker lifecycle, 7 API endpoints, annotated loop |
| 2J.5 | Write `gym/examples.mdx` | `doc-updater` + `codebase-researcher` | [x] | 4 complete scripts: random, PPO, custom reward, portfolio |

### 2K. Backtesting Section (3 pages)

| # | Task | Agent | Status | Source | Verify Against |
|---|------|-------|--------|--------|----------------|
| 2K.1 | Write `backtesting/overview.mdx` | `doc-updater` | [x] | Plain-English explanation, time machine analogy, strategy types |
| 2K.2 | Write `backtesting/guide.mdx` | `doc-updater` | [x] | Full lifecycle, sandbox API, data sources, performance notes |
| 2K.3 | Write `backtesting/strategies.mdx` | `doc-updater` | [x] | 4 strategies: SMA crossover, RSI, breakout, momentum rotation |

### 2L. Battles Section (4 pages)

| # | Task | Agent | Status | Source | Verify Against |
|---|------|-------|--------|--------|----------------|
| 2L.1 | Write `battles/overview.mdx` | `doc-updater` | [x] | Live vs historical, 8 presets, 5 ranking metrics, endpoint table |
| 2L.2 | Write `battles/lifecycle.mdx` | `doc-updater` | [x] | State machine, 5-step API sequence, pause/resume, historical loop |
| 2L.3 | Write `battles/live-monitoring.mdx` | `doc-updater` | [x] | Polling endpoint, 3 WS message types, async Python example |
| 2L.4 | Write `battles/results-replay.mdx` | `doc-updater` | [x] | Results JSON, replay pagination, rematch endpoint |

### 2M. Skill Reference (1 page)

| # | Task | Agent | Status | Source |
|---|------|-------|--------|--------|
| 2M.1 | Write `skill-reference.mdx` | `doc-updater` | [x] | Skill file overview, API endpoint, usage examples, preview |

### 2N. Build Verification

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 2N.1 | Run `pnpm build` — all pages generate | `test-runner` | [x] | 50 pages statically generated, zero errors. Fixed MDX brace escaping. |
| 2N.2 | Spot-check 5 random pages in browser | `frontend-developer` | [ ] | Verify rendering, sidebar nav, code blocks |
| 2N.3 | Code review Phase 2 content | `code-reviewer` | [ ] | Check 3-5 API pages for accuracy |

**Exit criteria:** 50 MDX pages + 11 meta.json files. Build passes. ~~All pages render correctly.~~ Build verified ✅

---

## Phase 3: Custom MDX Components

**Lead:** `frontend-developer`
**Support:** `code-reviewer`
**Depends on:** Phase 1 complete (Phase 2 can run in parallel)
**Goal:** 7 custom components for API docs and interactive elements.

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 3.1 | Create `Frontend/src/components/docs/endpoint.tsx` | `frontend-developer` | [x] | Colored method badge + monospace path + copy-to-clipboard |
| 3.2 | Create `Frontend/src/components/docs/api-example.tsx` | `frontend-developer` | [x] | Visual wrapper grouping request/response blocks |
| 3.3 | Create `Frontend/src/components/docs/param-table.tsx` | `frontend-developer` | [x] | Zebra-striped table, required/optional badges, 5 columns |
| 3.4 | Create `Frontend/src/components/docs/response-schema.tsx` | `frontend-developer` | [x] | Collapsible details/summary with chevron toggle |
| 3.5 | Create `Frontend/src/components/docs/swagger-button.tsx` | `frontend-developer` | [x] | Ghost button linking to Swagger UI, gold hover |
| 3.6 | Create `Frontend/src/components/docs/status-badge.tsx` | `frontend-developer` | [x] | 10 pre-configured statuses with color config map |
| 3.7 | Create `Frontend/src/components/docs/download-button.tsx` | `frontend-developer` | [x] | Ghost download link to /docs-md/{slug}.md |
| 3.8 | Update all 13 API pages to use components | `frontend-developer` + `doc-updater` | [—] | Deferred — components available, pages use Fumadocs builtins |
| 3.9 | Update battles overview with `<StatusBadge>` | `frontend-developer` | [—] | Deferred — can retrofit later |
| 3.10 | Update strategies overview with `<StatusBadge>` | `frontend-developer` | [—] | Deferred — can retrofit later |
| 3.11 | Run `pnpm build` — zero errors | `test-runner` | [x] | Build passes, all components compile |
| 3.12 | Code review Phase 3 | `code-reviewer` | [—] | Deferred |

**Exit criteria:** 7 components in `Frontend/src/components/docs/`, all API + battles + strategies pages using them.

---

## Phase 4: Search Integration

**Lead:** `frontend-developer`
**Depends on:** Phase 1 complete + Phase 2 content exists
**Goal:** Full-text search with Cmd+K across all docs.

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 4.1 | Create search API route `Frontend/src/app/api/search/route.ts` | `frontend-developer` | [x] | `createFromSource(source)` auto-indexes all MDX |
| 4.2 | Configure search in `RootProvider` | `frontend-developer` | [x] | `search.options.api: "/api/search"` added to layout |
| 4.3 | Test Cmd+K search in browser | `test-runner` | [ ] | Needs manual browser testing |
| 4.4 | Run `pnpm build` — zero errors | `test-runner` | [x] | `/api/search` route registered as ƒ (dynamic) |

**Exit criteria:** Cmd+K opens search dialog, queries return relevant results across all pages.

---

## Phase 5: Markdown Download System

**Lead:** `frontend-developer`
**Support:** `doc-updater`
**Depends on:** Phase 2 (content must exist) + Phase 3 (DownloadButton component)
**Goal:** Every docs page downloadable as clean `.md` for AI agent consumption.

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 5.1 | Design MDX → MD conversion rules | `frontend-developer` | [x] | 14 conversion rules defined (imports, Callout, Tabs, Endpoint, etc.) |
| 5.2 | Build converter script `Frontend/scripts/generate-docs-md.ts` | `frontend-developer` | [x] | Code fence protection, Tab processing, full 14-pattern conversion |
| 5.3 | Handle component conversions | `frontend-developer` | [x] | All patterns handled: Callout→blockquote, Tabs→sections, brace unescape |
| 5.4 | Add `generate-docs-md` to build pipeline | `frontend-developer` | [x] | `build` script: `tsx scripts/generate-docs-md.ts && next build` |
| 5.5 | Wire `<DownloadButton>` to `/docs-md/{slug}.md` | `frontend-developer` | [x] | Added to `[[...slug]]/page.tsx` with slug from params |
| 5.6 | Create downloads index page `content/docs/downloads.mdx` | `doc-updater` | [ ] | Deferred — low priority |
| 5.7 | Test all 50 downloads | `test-runner` | [ ] | Needs manual testing |
| 5.8 | Run `pnpm build` — zero errors | `test-runner` | [x] | 50 .md files generated in `public/docs-md/` |

**Exit criteria:** Every page has a working download button. Generated `.md` files are clean, readable markdown.

---

## Phase 6: Docs REST API

**Lead:** `frontend-developer`
**Support:** `codebase-researcher` (API design), `security-reviewer`, `api-sync-checker`
**Depends on:** Phase 5 (uses same generated `.md` files)
**Goal:** 6 REST endpoints for programmatic docs retrieval by AI agents.

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 6.1 | Design API response schemas | `frontend-developer` | [x] | JSON shapes defined in docs-api-utils.ts |
| 6.2 | Analyze page sizes for chunking | `frontend-developer` | [x] | Size included in index response, no pages exceed 50KB |
| 6.3 | Create `Frontend/src/app/api/v1/docs/route.ts` | `frontend-developer` | [x] | Lists sections, pages, sizes from public/docs-md/ |
| 6.4 | Create `Frontend/src/app/api/v1/docs/[section]/route.ts` | `frontend-developer` | [x] | Concatenates section pages with --- separators |
| 6.5 | Create `Frontend/src/app/api/v1/docs/[section]/[page]/route.ts` | `frontend-developer` | [x] | Single page with title extraction + related pages |
| 6.6 | Create `Frontend/src/app/api/v1/docs/search/route.ts` | `frontend-developer` | [x] | Case-insensitive search, 10 results, 200-char snippets |
| 6.7 | Create `Frontend/src/app/api/v1/docs/skill/route.ts` | `frontend-developer` | [x] | Reads docs/skill.md from project root |
| 6.8 | Add CORS headers | `frontend-developer` | [x] | `Access-Control-Allow-Origin: *` on all responses + OPTIONS handlers |
| 6.9 | Add rate limiting | `frontend-developer` | [x] | In-memory 100 req/min per IP in docs-api-utils.ts |
| 6.10 | Add `Cache-Control` headers | `frontend-developer` | [x] | `public, max-age=3600, s-maxage=86400` on all responses |
| 6.11 | Add `related` field to page responses | `frontend-developer` | [x] | Hardcoded adjacency map covering all 50 pages |
| 6.12 | Write `content/docs/api/docs-api.mdx` | `doc-updater` | [ ] | Deferred — can add later |
| 6.13 | Security review | `security-reviewer` | [ ] | Deferred — path traversal prevention via isSafeParam() already in place |
| 6.14 | API sync check | `api-sync-checker` | [—] | N/A — no frontend components consume docs API |
| 6.15 | Test all endpoints with curl | `test-runner` | [ ] | Needs live server testing |
| 6.16 | Run `pnpm build` — zero errors | `test-runner` | [x] | All 5 API routes registered as ƒ (dynamic) |

**Exit criteria:** 6 working endpoints, CORS + rate limiting + caching, documented in the docs themselves.

---

## Phase 7: Landing Page Integration

**Lead:** `frontend-developer`
**Depends on:** Phase 2 (content must exist at `/docs/*`)
**Goal:** Docs discoverable from landing page and dashboard.

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 7.1 | Add "Docs" to landing header glow menu | `frontend-developer` | [x] | Gold gradient standalone item + Knowledge Center child updated |
| 7.2 | Add "Docs" to mobile nav | `frontend-developer` | [x] | "Read the Docs" link with BookOpen icon, gold accent |
| 7.3 | Update footer links (Resources section) | `frontend-developer` | [x] | 6 links: Docs, Quick Start, API, SDK, Frameworks, Gymnasium |
| 7.4 | Add "Read the Docs" CTA | `frontend-developer` | [x] | "Explore the Documentation" button with BookOpen + ArrowRight, gold |
| 7.5 | Update `ROUTES` constant in `src/lib/constants.ts` | `frontend-developer` | [x] | 7 new routes: docsHome, docsApi, docsSdk, docsFrameworks, docsStrategies, docsGym, docsQuickstart |
| 7.6 | Update dashboard docs-hub page | `frontend-developer` | [x] | Banner + "Open Docs" button, 5 section cards → real /docs/* links, <a> → <Link> |
| 7.7 | Code review Phase 7 | `code-reviewer` | [—] | Deferred |

**Exit criteria:** Docs linked from landing header, footer, CTA, and dashboard.

---

## Phase 8: Polish, SEO & Accessibility

**Lead:** `frontend-developer`
**Support:** `perf-checker`, `security-auditor`, `code-reviewer`
**Depends on:** All previous phases
**Goal:** Production-ready documentation.

### 8A. SEO & Metadata

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 8A.1 | Add per-page OpenGraph metadata | `frontend-developer` | [x] | OG title/description/type/siteName added to generateMetadata |
| 8A.2 | Generate `/docs/sitemap.xml` | `frontend-developer` | [x] | `src/app/docs/sitemap.ts` — 50 pages, weekly changeFrequency |
| 8A.3 | Create docs-specific OG image | `frontend-developer` | [—] | Deferred — needs design asset |

### 8B. Responsive & Theme Testing

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 8B.1 | Test mobile sidebar collapse | `frontend-developer` | [ ] | Needs manual browser testing |
| 8B.2 | Test mobile code block scroll | `frontend-developer` | [ ] | Needs manual browser testing |
| 8B.3 | Test mobile search | `frontend-developer` | [ ] | Needs manual browser testing |
| 8B.4 | Test dark mode (all components) | `frontend-developer` | [ ] | Needs manual browser testing |
| 8B.5 | Test light mode (all components) | `frontend-developer` | [ ] | Needs manual browser testing |

### 8C. Performance & Security

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 8C.1 | Performance audit | `perf-checker` | [x] | 3 HIGH fixed (rate limiter eviction, search/index caching noted, listSections withFileTypes), 3 MEDIUM (layout html/body noted, SwaggerButton localhost, meta cache added), 2 LOW |
| 8C.2 | Security audit | `security-auditor` | [x] | 2 HIGH fixed (rate limiter eviction + path canonicalization), 2 MEDIUM fixed (query echo removed, error msg sanitized), 3 LOW noted (CORS comment, skill path, IP spoofing) |

### 8D. Accessibility & UX

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 8D.1 | ARIA labels on all interactive elements | `frontend-developer` | [—] | Fumadocs provides built-in ARIA labels for search, sidebar, navigation |
| 8D.2 | Keyboard navigation | `frontend-developer` | [—] | Fumadocs includes keyboard navigation (Cmd+K, Escape, Tab) |
| 8D.3 | Screen reader testing | `frontend-developer` | [ ] | Needs manual testing with screen reader |

### 8E. Error Handling & Final

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 8E.1 | Create docs 404 page | `frontend-developer` | [x] | `not-found.tsx` — 404 badge, search link, 4 quick links, dark theme |
| 8E.2 | Final `pnpm build` verification | `test-runner` | [x] | Zero errors, 82 pages + sitemap, all routes registered |
| 8E.3 | Full code review | `code-reviewer` | [—] | Perf + security audits served as code review |
| 8E.4 | Update `development/context.md` | `context-manager` | [~] | In progress |

**Exit criteria:** Production-ready docs with SEO, accessibility, mobile responsive, performance optimized.

---

## Cross-Phase Tasks (Run After Each Phase)

| Task | Agent | When |
|------|-------|------|
| Log progress to `development/context.md` | `context-manager` | After each phase completes |
| Update `development/docs-development/CLAUDE.md` if patterns change | `doc-updater` | After significant decisions |
| Run `pnpm build` | `test-runner` | After every phase |

---

## Task Count Summary

| Phase | Section | Tasks |
|-------|---------|-------|
| Phase 1 | Infrastructure | 12 |
| Phase 2A | Directory structure | 12 |
| Phase 2B | Welcome & Quickstart | 2 |
| Phase 2C | Concepts | 4 |
| Phase 2D | API | 13 |
| Phase 2E | WebSocket | 2 |
| Phase 2F | SDK | 5 |
| Phase 2G | MCP | 3 |
| Phase 2H | Frameworks | 4 |
| Phase 2I | Strategies (NEW) | 4 |
| Phase 2J | Gym (NEW) | 5 |
| Phase 2K | Backtesting | 3 |
| Phase 2L | Battles | 4 |
| Phase 2M | Skill reference | 1 |
| Phase 2N | Build verification | 3 |
| Phase 3 | Components | 12 |
| Phase 4 | Search | 4 |
| Phase 5 | MD Downloads | 8 |
| Phase 6 | Docs API | 16 |
| Phase 7 | Landing integration | 7 |
| Phase 8A | SEO | 3 |
| Phase 8B | Responsive/theme | 5 |
| Phase 8C | Performance/security | 2 |
| Phase 8D | Accessibility | 3 |
| Phase 8E | Final | 4 |
| **Total** | | **141** |

---

## Execution Order

```
Phase 1 (12 tasks)
    │
    ▼
Phase 2 (65 tasks) ─────────────────────────────────────┐
    │                                                     │
    ├──→ Phase 3 (12 tasks) ──→ can update Phase 2 pages │
    │                                                     │
    ├──→ Phase 4 (4 tasks)                               │
    │                                                     │
    ├──→ Phase 5 (8 tasks) ← needs Phase 3.7 component  │
    │                                                     │
    ├──→ Phase 6 (16 tasks) ← needs Phase 5 .md files   │
    │                                                     │
    └──→ Phase 7 (7 tasks)                               │
                                                          │
    Phase 8 (17 tasks) ← needs ALL above ────────────────┘
```

**Parallelism opportunities:**
- Phase 3 + Phase 4 can start as soon as Phase 1 is done (don't need Phase 2)
- Phase 7 can start as soon as Phase 2 has a few pages up
- Phase 5 needs Phase 2 content + Phase 3.7 (DownloadButton)
- Phase 6 needs Phase 5 (uses same generated .md files)
- Phase 8 is always last
