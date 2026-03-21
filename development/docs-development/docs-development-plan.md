---
type: plan
title: "Documentation Site — Full Development Plan"
status: complete
phase: docs
tags:
  - plan
  - docs
---

# Documentation Site — Full Development Plan

<!-- last-updated: 2026-03-19 -->

## Executive Summary

Build a **public-facing documentation site** for TradeReady.io with **three delivery modes**:

1. **Web UI** — Beautiful, searchable docs at `/docs` (Fumadocs + MDX)
2. **Downloadable Markdown** — Every page available as a `.md` file for humans to copy and give to AI agents
3. **REST API** — Programmatic docs retrieval endpoints for AI agent integration (chunked by section to fit context windows)

**Target audience:** AI agent developers building trading bots on our platform.

**Current state:** Empty scaffolding only — `Frontend/content/docs/` directories exist but contain zero files. No docs framework installed. No route handlers. Starting from scratch.

**Scope:** ~45 MDX pages across 12 sections, covering 110 REST endpoints, 58 MCP tools, 35 SDK methods, 7 Gymnasium environments, strategy system, training system, exchange abstraction.

---

## What Changed Since Previous Docs Plan

The previous plan (`development/docs-plan-task.md`) was written when the platform had ~90 endpoints and 43 MCP tools. Since then:

| Area | Previous | Current | Delta |
|------|----------|---------|-------|
| REST endpoints | ~90 | 110 | +20 (strategies, testing, training) |
| MCP tools | 43 | 58 | +15 |
| SDK methods | ~22 | 35 | +13 |
| Strategy system | — | Full CRUD + versioning + testing + recommendations | NEW |
| Training system | — | Run tracking, episodes, learning curves | NEW |
| Gymnasium wrapper | — | 7 envs, 5 rewards, 3 wrappers, 10 examples | NEW |
| Exchange abstraction | — | CCXT adapter, 110+ exchanges, symbol mapper | NEW |
| `docs/gym_api_guide.md` | — | Full gym API guide for RL developers | NEW |
| `docs/rate_limits.md` | — | Rate limit documentation | NEW |

---

## Technology Stack

| Component | Choice | Why |
|-----------|--------|-----|
| **Docs framework** | Fumadocs (`fumadocs-core` + `fumadocs-ui` + `fumadocs-mdx`) | Next.js 16 native, App Router, React 19, MDX, built-in search, used by shadcn/ui |
| **Search** | Fumadocs built-in (Orama under the hood) | Zero cost, client-side, auto-indexes MDX at build time |
| **Content format** | MDX files in `Frontend/content/docs/` | |
| **Code highlighting** | Shiki (built into Fumadocs) | `github-dark` theme |
| **Styling** | Fumadocs UI + custom CSS overrides | Dark-first, gold accent matching landing page |
| **Docs API** | Next.js Route Handlers (`/api/v1/docs/*`) | Same app, no extra infra |
| **MD downloads** | Static generation at build time OR on-demand from MDX source | |

### Packages to Install

```bash
cd Frontend
pnpm add fumadocs-core fumadocs-ui fumadocs-mdx
pnpm add -D @types/mdx
```

---

## Three Delivery Modes — Architecture

### Mode 1: Web UI (Human Browsing)

Standard Fumadocs site at `/docs`. Sidebar navigation, search (Cmd+K), code tabs, dark/light mode. This is the primary experience.

```
Browser → /docs/api/authentication → Fumadocs renders MDX → styled HTML
```

### Mode 2: Downloadable Markdown

Every docs page gets a "Download .md" button. Clicking it downloads the page content as a clean markdown file (stripped of MDX components, replaced with standard markdown equivalents).

**Implementation options:**
- **Option A (Build-time):** Generate `.md` versions of every page during `pnpm build` into `public/docs-md/`. Simple, fast, zero runtime cost.
- **Option B (On-demand):** API route that reads the MDX source, strips JSX components, returns as `text/markdown` with `Content-Disposition: attachment`.

**Recommendation:** Option A (build-time) for simplicity. A build script processes each MDX file → strips imports/JSX → writes to `public/docs-md/{path}.md`. The download button links to `/docs-md/{path}.md`.

```
Button click → /docs-md/api/authentication.md → static file download
```

### Mode 3: REST API (Programmatic Retrieval)

New API routes under `/api/v1/docs/` that return documentation content as JSON. Designed for AI agent retrieval.

**Key design decision: Chunking for context windows.**

A single dump of all docs would be ~200KB+ of text — too large for most LLM context windows. Instead, docs are split into logical sections that can be fetched individually.

#### API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/api/v1/docs` | List all available doc sections with metadata (title, description, path, size_bytes) | Public |
| GET | `/api/v1/docs/{section}` | Get a specific section's content as markdown | Public |
| GET | `/api/v1/docs/{section}/{page}` | Get a specific page's content as markdown | Public |
| GET | `/api/v1/docs/search?q=` | Search docs content, return matching sections with snippets | Public |
| GET | `/api/v1/docs/skill` | Get the full skill.md file (for LLM system prompts) | Public |
| GET | `/api/v1/docs/quickstart` | Shortcut: get the quickstart guide | Public |

#### Response Format

```json
// GET /api/v1/docs
{
  "sections": [
    {
      "id": "api",
      "title": "REST API Reference",
      "description": "All 110 REST endpoints with examples",
      "pages": [
        {"id": "authentication", "title": "Authentication", "path": "/api/v1/docs/api/authentication", "size_bytes": 4200},
        {"id": "market-data", "title": "Market Data", "path": "/api/v1/docs/api/market-data", "size_bytes": 6800}
      ],
      "total_size_bytes": 45000
    }
  ],
  "total_pages": 45,
  "total_size_bytes": 180000
}

// GET /api/v1/docs/api/authentication
{
  "section": "api",
  "page": "authentication",
  "title": "Authentication",
  "content": "# Authentication\n\nTradeReady.io supports two authentication methods...",
  "format": "markdown",
  "size_bytes": 4200,
  "related": ["api/errors", "api/rate-limits", "sdk/installation"]
}
```

#### Where to implement

**Option A (Frontend — Next.js Route Handlers):** Routes at `Frontend/src/app/api/v1/docs/` that read MDX source files, strip JSX, return markdown. Pros: same deployment, access to MDX source. Cons: docs API tied to frontend deployment.

**Option B (Backend — FastAPI):** Routes at `src/api/routes/docs.py` that read from a `docs_content/` directory of pre-built markdown files. Pros: docs API lives with the rest of the API, consistent auth/rate-limiting. Cons: need a build step to sync content.

**Recommendation:** Option A (Frontend Route Handlers). The MDX source files are in the Frontend project. Reading them directly avoids a sync step. The `/api/v1/docs/*` prefix makes it feel like part of the main API even though it's served by Next.js. We can add CORS headers for cross-origin agent access.

---

## Documentation Structure (Sitemap)

### Sections and Pages (~45 pages, 12 sections)

```
/docs                              → Welcome / Overview
/docs/quickstart                   → 5-Minute Quickstart

/docs/concepts                     → Section: Core Concepts
  /how-it-works                    → Platform architecture (user-facing)
  /agents                          → What are agents, multi-agent model
  /trading-rules                   → Fees, slippage, position limits
  /risk-management                 → Circuit breaker, rate limits, daily loss limits

/docs/api                          → Section: REST API (110 endpoints)
  /authentication                  → API keys, JWT, auth flow
  /market-data                     → GET /market/* (8 endpoints)
  /trading                         → POST /trade/* (7 endpoints)
  /account                         → GET /account/* (7 endpoints)
  /analytics                       → GET /analytics/* (3 endpoints)
  /agents                          → Agent management (14 endpoints, JWT only)
  /strategies                      → Strategy CRUD + deploy (10 endpoints) [NEW]
  /strategy-testing                → Strategy test runs (7 endpoints) [NEW]
  /training                        → Training run observation (7 endpoints) [NEW]
  /battles                         → Battle system (20 endpoints, JWT only)
  /backtesting                     → Backtest engine (24 endpoints)
  /errors                          → Error codes & handling
  /rate-limits                     → Rate limit tiers & headers

/docs/websocket                    → Section: WebSocket
  /connection                      → Connection, auth, heartbeat
  /channels                        → Ticker, candles, orders, portfolio, battles

/docs/sdk                          → Section: Python SDK (35 methods)
  /installation                    → pip install, setup
  /sync-client                     → AgentExchangeClient (35 methods)
  /async-client                    → AsyncAgentExchangeClient
  /websocket-client                → AgentExchangeWS streaming
  /error-handling                  → Exception hierarchy (10 classes)

/docs/mcp                          → Section: MCP Server (58 tools)
  /overview                        → What is MCP, how it works
  /setup                           → Claude Desktop / Cline configuration
  /tools                           → All 58 tools by category

/docs/frameworks                   → Section: Framework Guides
  /langchain                       → LangChain integration
  /crewai                          → CrewAI integration
  /agent-zero                      → Agent Zero integration
  /openclaw                        → OpenClaw integration

/docs/strategies                   → Section: Strategy Development [NEW]
  /overview                        → What are strategies, lifecycle, JSON definition
  /indicators                      → 7 built-in indicators (RSI, MACD, SMA, EMA, BB, ADX, ATR)
  /testing                         → Multi-episode testing, recommendations engine
  /deployment                      → Deploy to live, monitor, undeploy

/docs/gym                          → Section: Gymnasium / RL Training [NEW]
  /overview                        → What is tradeready-gym, installation
  /environments                    → 7 registered environments
  /rewards                         → 5 reward functions
  /training-tracking               → TrainingTracker, reporting to platform
  /examples                        → PPO, DQN, custom reward, portfolio, live

/docs/backtesting                  → Section: Backtesting
  /overview                        → What is backtesting (plain English)
  /guide                           → Technical guide (lifecycle, sandbox API)
  /strategies                      → Strategy examples (MA, RSI, breakout, momentum)

/docs/battles                      → Section: Agent Battles
  /overview                        → What are battles, presets
  /lifecycle                       → Create → start → monitor → results
  /live-monitoring                 → WebSocket events, real-time data
  /results-replay                  → Results, rankings, equity replay

/docs/skill-reference              → Full skill.md (viewable + downloadable)
```

**Total: ~45 pages** in 12 sections (vs. 35 pages in 10 sections previously).

**New sections vs. old plan:**
- `/docs/api/strategies` — 10 strategy CRUD endpoints
- `/docs/api/strategy-testing` — 7 test endpoints
- `/docs/api/training` — 7 training endpoints
- `/docs/strategies/` — 4-page section on the strategy system
- `/docs/gym/` — 5-page section on Gymnasium / RL training

---

## UI Design

### Layout (Same as previous plan — proven design)

```
┌──────────────────────────────────────────────────────┐
│  Header: TradeReady.io logo │ Docs │ API │ SDK       │
│          Search (⌘K)        │ GitHub │ Get Started    │
├───────────┬──────────────────────────────────────────┤
│  Sidebar  │  Content Area                             │
│           │                                           │
│  Overview │  # Page Title          [Download .md ↓]  │
│  Quick... │                                           │
│           │  Content with code blocks, tables,        │
│  Concepts │  callouts, tabs (curl/python/sdk),        │
│   ├ How.. │  copy buttons, syntax highlighting        │
│   ├ Agen. │                                           │
│   └ Risk  │                          ┌──────────────┐│
│           │                          │ On This Page  ││
│  API      │                          │ • Section 1   ││
│   ├ Auth  │                          │ • Section 2   ││
│   ├ Mark. │                          │ • Section 3   ││
│   ...     │                          └──────────────┘│
│           │                                           │
│ Strat. ★  │  ← Prev Page    Next Page →               │
│ Gym    ★  │                                           │
│ SDK      │                                           │
│ MCP      │  ★ = NEW sections                         │
└───────────┴──────────────────────────────────────────┘
```

### Design Tokens

- **Background:** `hsl(var(--background))` — dark navy
- **Sidebar:** `hsl(var(--card))` with border
- **Accent:** Gold (`hsl(var(--accent))`) for links, active states
- **Code blocks:** Shiki `github-dark` theme
- **Font:** Inter (body), JetBrains Mono (code)
- **Download button:** Subtle ghost button with download icon, top-right of content area

### Key UI Features

1. **Command-K search** — Full-text search across all docs
2. **Code tabs** — curl / Python SDK / MCP side by side
3. **Copy button** — On every code block
4. **Download .md button** — Top of every page, downloads the page as markdown
5. **Breadcrumbs** — Full path navigation
6. **Table of Contents** — Right sidebar with scrollspy
7. **Previous/Next** — Page navigation
8. **Dark/Light mode** — Synced with landing page theme
9. **Mobile responsive** — Hamburger sidebar
10. **API badge components** — Method badges (GET/POST/PUT/DELETE), parameter tables, response schemas

### Custom MDX Components (to build)

| Component | Description |
|-----------|-------------|
| `<Endpoint method="GET" path="/market/price/{symbol}" />` | Styled method badge + path |
| `<ApiExample>` | Tabbed request/response (curl / Python / SDK) |
| `<ParamTable>` | Parameter table (name, type, required, description) |
| `<ResponseSchema>` | Collapsible JSON response with field descriptions |
| `<SwaggerButton>` | "Try in Swagger" link |
| `<StatusBadge status="active" />` | Colored status badges |
| `<DownloadButton />` | Download current page as .md |
| `<IndicatorChart />` | Visual indicator examples for strategy docs |

---

## Phase Breakdown & Agent Assignments

### Phase 1: Infrastructure Setup
**Lead: frontend-developer**
**Support: code-reviewer, test-runner**
**Duration estimate: 1 session**

| # | Task | Agent | Details |
|---|------|-------|---------|
| 1.1 | Install Fumadocs packages | frontend-developer | `fumadocs-core`, `fumadocs-ui`, `fumadocs-mdx`, `@types/mdx` |
| 1.2 | Create `source.config.ts` | frontend-developer | Fumadocs content source config → `Frontend/content/docs/` |
| 1.3 | Update `next.config.ts` | frontend-developer | Add `createMDX()` wrapper |
| 1.4 | Create docs layout | frontend-developer | `Frontend/src/app/docs/layout.tsx` with DocsLayout, sidebar, brand theming |
| 1.5 | Create catch-all page | frontend-developer | `Frontend/src/app/docs/[[...slug]]/page.tsx` — MDX renderer |
| 1.6 | Create first content file | frontend-developer | `Frontend/content/docs/index.mdx` — welcome page |
| 1.7 | Configure theme | frontend-developer | Dark-first, gold accent, docs-theme.css overrides |
| 1.8 | Create `source.ts` loader | frontend-developer | `Frontend/src/lib/source.ts` |
| 1.9 | Verify routing | frontend-developer | `/docs` is public (outside `(dashboard)` group, no auth) |
| 1.10 | Test build | test-runner | `pnpm build` passes with docs route |

**Deliverable:** `/docs` renders a welcome page with Fumadocs sidebar and search.

---

### Phase 2: Content Migration — Core Docs
**Lead: doc-updater**
**Support: codebase-researcher (for accuracy), frontend-developer (MDX formatting)**
**Duration estimate: 2-3 sessions**

This is the largest phase. Every page must be written from the current source of truth (code + existing markdown files in `docs/`).

| # | Task | Agent | Source → Target |
|---|------|-------|-----------------|
| 2.1 | Create directory structure | doc-updater | All section folders + `meta.json` sidebar configs |
| 2.2 | Welcome page | doc-updater | Write `index.mdx` — platform overview, 3 delivery modes explained |
| 2.3 | Quickstart | doc-updater | `docs/quickstart.md` → `quickstart.mdx` |
| 2.4 | Concepts section (4 pages) | doc-updater | Extract from `docs/skill.md` → 4 MDX files |
| 2.5 | API section (13 pages) | doc-updater + codebase-researcher | `docs/api_reference.md` + route files → 13 MDX files (incl. 3 NEW: strategies, strategy-testing, training) |
| 2.6 | WebSocket section (2 pages) | doc-updater | `docs/skill.md` + `src/api/websocket/` → 2 MDX files |
| 2.7 | SDK section (5 pages) | doc-updater | `sdk/README.md` + `sdk/CLAUDE.md` → 5 MDX files |
| 2.8 | MCP section (3 pages) | doc-updater | `docs/mcp_server.md` → 3 MDX files |
| 2.9 | Framework guides (4 pages) | doc-updater | `docs/framework_guides/*.md` → 4 MDX files |
| 2.10 | Strategy section (4 pages) [NEW] | doc-updater + codebase-researcher | `src/strategies/CLAUDE.md` + route files → 4 MDX files |
| 2.11 | Gym section (5 pages) [NEW] | doc-updater + codebase-researcher | `docs/gym_api_guide.md` + `tradeready-gym/` → 5 MDX files |
| 2.12 | Backtesting section (3 pages) | doc-updater | `docs/backtesting-guide.md` + `docs/backtesting-explained.md` → 3 MDX files |
| 2.13 | Battles section (4 pages) | doc-updater | `docs/skill.md` + `src/battles/CLAUDE.md` → 4 MDX files |
| 2.14 | Skill reference page | doc-updater | `docs/skill.md` → `skill-reference.mdx` with download button |
| 2.15 | Configure all `meta.json` | doc-updater | Sidebar ordering and labels for all 12 sections |

**Content sources:**
- `docs/skill.md` (1,636 lines) — primary source for concepts, trading rules, risk, WebSocket
- `docs/api_reference.md` — primary source for all API endpoints
- `docs/quickstart.md` — quickstart guide
- `docs/mcp_server.md` — MCP server reference
- `docs/backtesting-guide.md` + `docs/backtesting-explained.md` — backtesting
- `docs/gym_api_guide.md` — gymnasium guide
- `docs/rate_limits.md` — rate limit details
- `docs/framework_guides/*.md` — 4 framework guides
- `sdk/README.md` — SDK reference
- `src/strategies/CLAUDE.md` — strategy system internals (extract user-facing parts)
- `src/training/CLAUDE.md` — training system internals (extract user-facing parts)
- `development/Gym_api/gym_strategy_docs.md` — additional gym docs

**Accuracy verification:** codebase-researcher validates every endpoint, parameter, and response example against actual route code before doc-updater writes the page.

**Deliverable:** 45 MDX pages, all rendering correctly at `/docs/*`.

---

### Phase 3: Custom MDX Components
**Lead: frontend-developer**
**Support: code-reviewer**
**Duration estimate: 1 session**

| # | Task | Agent | Details |
|---|------|-------|---------|
| 3.1 | Endpoint component | frontend-developer | `<Endpoint method="GET" path="..." />` — method badge + path |
| 3.2 | ApiExample component | frontend-developer | Tabbed code blocks (curl / Python / SDK) with copy buttons |
| 3.3 | ParamTable component | frontend-developer | Parameter table with name, type, required, description |
| 3.4 | ResponseSchema component | frontend-developer | Collapsible JSON with field annotations |
| 3.5 | SwaggerButton component | frontend-developer | Link to Swagger UI |
| 3.6 | StatusBadge component | frontend-developer | Colored badges for states |
| 3.7 | DownloadButton component | frontend-developer | Downloads current page as .md file |
| 3.8 | Update API pages to use components | frontend-developer + doc-updater | Retrofit all 13 API pages with the new components |

**Deliverable:** 7 custom components in `Frontend/src/components/docs/`, all API pages using them.

---

### Phase 4: Search Integration
**Lead: frontend-developer**
**Duration estimate: 0.5 session**

| # | Task | Agent | Details |
|---|------|-------|---------|
| 4.1 | Create search API route | frontend-developer | `Frontend/src/app/api/search/route.ts` using `createFromSource` |
| 4.2 | Configure RootProvider | frontend-developer | Search options in docs layout |
| 4.3 | Test search | test-runner | Verify Cmd+K works, all pages indexed |

**Deliverable:** Full-text search working across all 45 pages.

---

### Phase 5: Markdown Download System
**Lead: frontend-developer**
**Support: doc-updater**
**Duration estimate: 1 session**

| # | Task | Agent | Details |
|---|------|-------|---------|
| 5.1 | Build MDX-to-MD converter | frontend-developer | Script that reads `.mdx` files, strips JSX imports/components, converts to clean markdown |
| 5.2 | Build generation script | frontend-developer | `scripts/generate-docs-md.ts` — runs converter on all MDX files, outputs to `public/docs-md/` |
| 5.3 | Add to build pipeline | frontend-developer | Run script during `pnpm build` (or as `prebuild` script) |
| 5.4 | Add DownloadButton to layout | frontend-developer | Every page gets a download button linking to `/docs-md/{slug}.md` |
| 5.5 | Add download index page | doc-updater | `/docs/downloads` page listing all available .md files with sizes |
| 5.6 | Test downloads | test-runner | Every page downloads correctly, markdown renders properly |

**MDX → MD conversion rules:**
- Strip `import` statements
- Convert `<Callout type="info">` → `> **Info:** ...`
- Convert `<Tabs>/<Tab>` → sequential code blocks with headers
- Convert `<Endpoint>` → `### GET /path/to/endpoint`
- Convert `<ParamTable>` → markdown table
- Convert `<ResponseSchema>` → JSON code block
- Preserve all standard markdown (headings, lists, code blocks, tables, links)

**Deliverable:** Every docs page downloadable as clean `.md`, index page listing all files.

---

### Phase 6: Docs REST API
**Lead: frontend-developer**
**Support: codebase-researcher (API design), api-sync-checker, security-reviewer**
**Duration estimate: 1-2 sessions**

| # | Task | Agent | Details |
|---|------|-------|---------|
| 6.1 | Design API schema | codebase-researcher | Finalize response shapes, pagination, size limits |
| 6.2 | Create docs API routes | frontend-developer | Next.js Route Handlers at `Frontend/src/app/api/v1/docs/` |
| 6.3 | GET `/api/v1/docs` | frontend-developer | List all sections with metadata and page sizes |
| 6.4 | GET `/api/v1/docs/[section]` | frontend-developer | Get full section content as markdown |
| 6.5 | GET `/api/v1/docs/[section]/[page]` | frontend-developer | Get single page content as markdown |
| 6.6 | GET `/api/v1/docs/search` | frontend-developer | Search docs, return matching snippets |
| 6.7 | GET `/api/v1/docs/skill` | frontend-developer | Return full skill.md content |
| 6.8 | Add CORS headers | frontend-developer | Allow cross-origin requests for agent retrieval |
| 6.9 | Add rate limiting | frontend-developer | Prevent abuse (100 req/min per IP) |
| 6.10 | Add response caching | frontend-developer | `Cache-Control` headers, revalidate on deploy |
| 6.11 | Size analysis | codebase-researcher | Analyze page sizes, flag any > 50KB, recommend chunking |
| 6.12 | Document the docs API | doc-updater | Add a "Docs API" page to the docs explaining how to use the API |
| 6.13 | Security review | security-reviewer | CORS, rate limiting, no sensitive data exposure |

**Size budget per page:** Target < 20KB per page markdown. If any page exceeds 50KB, split into sub-pages. The `/api/v1/docs` index endpoint includes `size_bytes` per page so agents can budget their context window.

**Caching strategy:**
- `Cache-Control: public, max-age=3600, s-maxage=86400` (1hr client, 24hr CDN)
- `ETag` based on content hash
- Revalidates on each deployment (content changes = new build)

**Deliverable:** 6 REST endpoints serving docs as markdown JSON, with CORS + rate limiting + caching.

---

### Phase 7: Landing Page Integration
**Lead: frontend-developer**
**Duration estimate: 0.5 session**

| # | Task | Agent | Details |
|---|------|-------|---------|
| 7.1 | Add "Docs" to landing header | frontend-developer | Glow menu nav item with BookOpen icon |
| 7.2 | Update footer links | frontend-developer | Replace `#` hrefs → real `/docs/*` routes |
| 7.3 | Add "Read the Docs" CTA | frontend-developer | Gold-accent link in CTA section |
| 7.4 | Update ROUTES constant | frontend-developer | Add docs routes to `src/lib/constants.ts` |
| 7.5 | Update dashboard docs page | frontend-developer | `/docs-hub` banner linking to public `/docs` |

**Deliverable:** Docs discoverable from landing page nav, footer, and CTA.

---

### Phase 8: Polish, SEO & Accessibility
**Lead: frontend-developer**
**Support: code-reviewer, perf-checker, security-auditor**
**Duration estimate: 1 session**

| # | Task | Agent | Details |
|---|------|-------|---------|
| 8.1 | OpenGraph metadata | frontend-developer | Per-page titles, descriptions |
| 8.2 | Generate sitemap | frontend-developer | Auto-generate `/docs/sitemap.xml` |
| 8.3 | OG image | frontend-developer | Docs-specific Open Graph image |
| 8.4 | Mobile testing | frontend-developer | Sidebar collapse, code scroll, search |
| 8.5 | Dark/light mode testing | frontend-developer | All components work in both themes |
| 8.6 | Performance audit | perf-checker | Bundle size impact, lazy loading |
| 8.7 | Accessibility audit | frontend-developer | ARIA labels, keyboard nav, screen reader |
| 8.8 | Custom 404 page | frontend-developer | Docs 404 with search + popular links |
| 8.9 | Code review | code-reviewer | Full pass on all docs infrastructure |

**Deliverable:** Production-ready docs with SEO, accessibility, and performance optimized.

---

## Phase Dependencies

```
Phase 1 (Setup) ──────→ Phase 2 (Content) ──────→ Phase 7 (Landing Integration)
                              │
                              ├──→ Phase 3 (Components) ──→ Phase 8 (Polish)
                              │
                              ├──→ Phase 4 (Search)
                              │
                              ├──→ Phase 5 (MD Downloads)
                              │
                              └──→ Phase 6 (Docs API)
```

**Phase 1** must complete first (infrastructure).
**Phase 2** must complete second (content).
**Phases 3, 4, 5, 6, 7** can run in parallel after Phase 2.
**Phase 8** runs last (requires everything else).

---

## Agent Responsibility Matrix

| Agent | Primary Responsibilities | Phases |
|-------|------------------------|--------|
| **frontend-developer** | Fumadocs setup, layout, components, API routes, download system, landing integration, SEO | 1, 3, 4, 5, 6, 7, 8 |
| **doc-updater** | All MDX content writing, meta.json configs, content accuracy | 2, 5 |
| **codebase-researcher** | Verify endpoint details, validate examples, analyze page sizes, API design input | 2, 6 |
| **code-reviewer** | Review all code changes | 1, 3, 8 |
| **test-runner** | Build verification, search testing, download testing | 1, 4, 5 |
| **security-reviewer** | Docs API security (CORS, rate limiting) | 6 |
| **api-sync-checker** | Verify docs API types match frontend | 6 |
| **perf-checker** | Bundle size, lazy loading impact | 8 |
| **context-manager** | Log progress after each phase | All |

---

## Content Guidelines

### What Goes in Docs (User-Facing)

- How to register, authenticate (API key vs JWT)
- All 110 REST endpoints with request/response examples
- WebSocket protocol with subscribe/unsubscribe examples
- Python SDK (35 methods, sync + async + streaming)
- MCP Server setup (58 tools across 10 categories)
- Framework integrations (LangChain, CrewAI, Agent Zero, OpenClaw)
- Strategy development (JSON definitions, indicators, testing, deployment)
- Gymnasium environments (installation, environments, rewards, examples)
- Training observation (run tracking, learning curves)
- Backtesting (lifecycle, sandbox API, strategy examples)
- Battles (presets, lifecycle, live monitoring, results)
- Trading rules (fees, slippage, position limits, circuit breaker)
- Error codes and handling
- Rate limits and best practices
- Skill file (downloadable reference for AI agents)

### What Does NOT Go in Docs (Internal)

- Database schemas, migrations, Alembic commands
- Internal service/repository architecture
- Middleware chain, dependency injection
- Docker/infrastructure setup
- Celery task internals
- CI/CD pipeline
- Monitoring setup (Prometheus, Grafana)
- Test infrastructure

### Tone & Style

- **Audience:** Developer building AI trading agents (human or LLM)
- **Tone:** Clear, direct, technical but approachable
- **Code examples:** Always working code, never pseudocode
- **Every API page:** Method + path + description + parameters + example request + example response + error cases
- **Strategy/Gym pages:** Concept explanation + code example + tips

---

## File Structure (Final)

```
Frontend/
├── content/
│   └── docs/
│       ├── index.mdx                         # Welcome + 3 delivery modes
│       ├── quickstart.mdx                    # 5-minute quickstart
│       ├── meta.json                         # Root sidebar config
│       ├── concepts/                         # 4 pages
│       │   ├── meta.json
│       │   ├── how-it-works.mdx
│       │   ├── agents.mdx
│       │   ├── trading-rules.mdx
│       │   └── risk-management.mdx
│       ├── api/                              # 13 pages
│       │   ├── meta.json
│       │   ├── authentication.mdx
│       │   ├── market-data.mdx
│       │   ├── trading.mdx
│       │   ├── account.mdx
│       │   ├── analytics.mdx
│       │   ├── agents.mdx
│       │   ├── strategies.mdx               # NEW
│       │   ├── strategy-testing.mdx          # NEW
│       │   ├── training.mdx                  # NEW
│       │   ├── battles.mdx
│       │   ├── backtesting.mdx
│       │   ├── errors.mdx
│       │   └── rate-limits.mdx
│       ├── websocket/                        # 2 pages
│       │   ├── meta.json
│       │   ├── connection.mdx
│       │   └── channels.mdx
│       ├── sdk/                              # 5 pages
│       │   ├── meta.json
│       │   ├── installation.mdx
│       │   ├── sync-client.mdx
│       │   ├── async-client.mdx
│       │   ├── websocket-client.mdx
│       │   └── error-handling.mdx
│       ├── mcp/                              # 3 pages
│       │   ├── meta.json
│       │   ├── overview.mdx
│       │   ├── setup.mdx
│       │   └── tools.mdx
│       ├── frameworks/                       # 4 pages
│       │   ├── meta.json
│       │   ├── langchain.mdx
│       │   ├── crewai.mdx
│       │   ├── agent-zero.mdx
│       │   └── openclaw.mdx
│       ├── strategies/                       # 4 pages [NEW SECTION]
│       │   ├── meta.json
│       │   ├── overview.mdx
│       │   ├── indicators.mdx
│       │   ├── testing.mdx
│       │   └── deployment.mdx
│       ├── gym/                              # 5 pages [NEW SECTION]
│       │   ├── meta.json
│       │   ├── overview.mdx
│       │   ├── environments.mdx
│       │   ├── rewards.mdx
│       │   ├── training-tracking.mdx
│       │   └── examples.mdx
│       ├── backtesting/                      # 3 pages
│       │   ├── meta.json
│       │   ├── overview.mdx
│       │   ├── guide.mdx
│       │   └── strategies.mdx
│       ├── battles/                          # 4 pages
│       │   ├── meta.json
│       │   ├── overview.mdx
│       │   ├── lifecycle.mdx
│       │   ├── live-monitoring.mdx
│       │   └── results-replay.mdx
│       └── skill-reference.mdx              # Full skill.md
├── public/
│   └── docs-md/                             # Generated .md files (build-time)
│       ├── index.md
│       ├── quickstart.md
│       ├── api/
│       │   ├── authentication.md
│       │   └── ...
│       └── ...
├── scripts/
│   └── generate-docs-md.ts                  # MDX → MD converter script
├── source.config.ts                          # Fumadocs content source
├── src/
│   ├── app/
│   │   ├── docs/                            # Public docs route (NO auth)
│   │   │   ├── layout.tsx                   # Fumadocs DocsLayout + theme
│   │   │   ├── docs-theme.css               # Brand overrides
│   │   │   └── [[...slug]]/
│   │   │       └── page.tsx                 # Fumadocs MDX renderer
│   │   └── api/
│   │       ├── search/
│   │       │   └── route.ts                 # Fumadocs search index
│   │       └── v1/
│   │           └── docs/
│   │               ├── route.ts             # GET /api/v1/docs — list sections
│   │               ├── skill/
│   │               │   └── route.ts         # GET /api/v1/docs/skill
│   │               ├── search/
│   │               │   └── route.ts         # GET /api/v1/docs/search
│   │               └── [section]/
│   │                   ├── route.ts         # GET /api/v1/docs/{section}
│   │                   └── [page]/
│   │                       └── route.ts     # GET /api/v1/docs/{section}/{page}
│   ├── components/
│   │   └── docs/
│   │       ├── endpoint.tsx
│   │       ├── api-example.tsx
│   │       ├── param-table.tsx
│   │       ├── response-schema.tsx
│   │       ├── swagger-button.tsx
│   │       ├── status-badge.tsx
│   │       └── download-button.tsx
│   └── lib/
│       └── source.ts                        # Fumadocs content loader
└── next.config.ts                           # Updated with createMDX()
```

---

## Task Summary

| Phase | Tasks | Description | Primary Agent |
|-------|-------|-------------|---------------|
| **Phase 1** | 10 | Fumadocs setup, routing, theme, first page | frontend-developer |
| **Phase 2** | 15 | Migrate + write all content (~45 MDX pages) | doc-updater |
| **Phase 3** | 8 | Custom API docs components + DownloadButton | frontend-developer |
| **Phase 4** | 3 | Full-text search (Cmd+K) | frontend-developer |
| **Phase 5** | 6 | Markdown download system (build-time generation) | frontend-developer |
| **Phase 6** | 13 | Docs REST API (6 endpoints + caching + security) | frontend-developer |
| **Phase 7** | 5 | Landing page + dashboard integration | frontend-developer |
| **Phase 8** | 9 | SEO, accessibility, performance, polish | frontend-developer |
| **Total** | **69 tasks** | | |

### Priority Order

1. **Phase 1** → Infrastructure (must be first)
2. **Phase 2** → Content (core value)
3. **Phase 3** → Components (enhances content)
4. **Phase 4** → Search (usability)
5. **Phase 5** → MD Downloads (second delivery mode)
6. **Phase 6** → Docs API (third delivery mode)
7. **Phase 7** → Landing integration (discoverability)
8. **Phase 8** → Polish (production readiness)

---

## Execution Notes

### For the Team Lead (orchestrating)

- **Phase 1:** Deploy frontend-developer. Verify build passes before moving on.
- **Phase 2:** Deploy doc-updater with codebase-researcher for accuracy. This is the longest phase. Can split into sub-sessions by section.
- **Phases 3-7:** Can parallelize. Deploy frontend-developer on 3+4+5+6+7 while doc-updater handles content updates from Phase 3.8.
- **Phase 8:** Final pass. All agents review their areas.
- **After each phase:** Deploy context-manager to log progress.

### Content Accuracy Protocol

For every API endpoint documented:
1. codebase-researcher reads the actual route handler code
2. codebase-researcher reads the Pydantic request/response schemas
3. doc-updater writes the MDX page using verified data
4. code-reviewer spot-checks 3-5 endpoints per section

### Build Verification

After each phase, run:
```bash
cd Frontend && pnpm build
```
Zero errors required before proceeding to next phase.
