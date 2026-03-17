# Documentation Site — Plan & Task Breakdown

## Overview

Build a **public-facing documentation site** for TradeReady.io, accessible from the landing page (no auth required). The docs target **AI agent developers** — the end-users who build trading bots on our platform.

**Current state:** Docs exist only inside the authenticated dashboard (`/docs`). The landing page footer has placeholder `#` links for "API Docs", "Python SDK", "Framework Guides". Raw markdown files exist in `/docs/` but aren't served publicly.

**Target state:** A beautiful, searchable, public `/docs` route powered by **Fumadocs** (Next.js native MDX docs framework), integrated into the existing Next.js app.

---

## Technology Choice: Fumadocs

| Criteria | Decision |
|----------|----------|
| **Framework** | Fumadocs (`fumadocs-core` + `fumadocs-ui` + `fumadocs-mdx`) |
| **Why** | Next.js 16 native, App Router, React 19 compatible, MDX, built-in search, dark/light mode, code highlighting, used by shadcn/ui |
| **Search** | Orama (open-source, zero cost, client-side full-text search) |
| **Content format** | MDX files in `Frontend/content/docs/` |
| **Styling** | Fumadocs UI theme customized to match TradeReady.io brand (dark-first, accent gold) |
| **Alternatives rejected** | Nextra (too rigid), Docusaurus (separate app), Mintlify (hosted/paid), Starlight (Astro, separate app) |

### Packages to Install

```bash
cd Frontend
pnpm add fumadocs-core fumadocs-ui fumadocs-mdx
pnpm add -D @types/mdx
```

---

## Documentation Structure (Information Architecture)

What goes in docs (end-user facing):
- Getting started, quickstart, registration
- API reference (REST endpoints, auth, errors, rate limits)
- WebSocket protocol
- Python SDK usage
- MCP Server setup (Claude Desktop, Cline)
- Framework integrations (LangChain, CrewAI, Agent Zero, OpenClaw)
- Backtesting guide
- Agent management
- Battle system
- Trading rules & risk management
- Skill file reference

What does NOT go in docs (internal):
- Database schemas, migrations, Alembic
- Internal architecture (middleware chain, dependency injection)
- Repository/service layer details
- Docker/infrastructure setup (dev-only)
- CI/CD pipeline details

### Sitemap

```
/docs                           → Welcome / Overview
/docs/quickstart                → 5-Minute Quickstart
│
/docs/concepts                  → Section: Core Concepts
/docs/concepts/how-it-works     → How the platform works
/docs/concepts/agents           → What are agents
/docs/concepts/trading-rules    → Fees, slippage, limits
/docs/concepts/risk-management  → Position limits, circuit breaker, rate limits
│
/docs/api                       → Section: REST API
/docs/api/authentication        → API keys, JWT, auth flow
/docs/api/market-data           → GET /market/* endpoints
/docs/api/trading               → POST /trade/* endpoints
/docs/api/account               → GET /account/* endpoints
/docs/api/analytics             → GET /analytics/* endpoints
/docs/api/agents                → Agent management endpoints (JWT only)
/docs/api/battles               → Battle system endpoints (JWT only)
/docs/api/errors                → Error codes & handling
/docs/api/rate-limits           → Rate limit tiers & headers
│
/docs/websocket                 → Section: WebSocket
/docs/websocket/connection      → Connection, auth, heartbeat
/docs/websocket/channels        → Ticker, candles, orders, portfolio, battles
│
/docs/sdk                       → Section: Python SDK
/docs/sdk/installation          → pip install, setup
/docs/sdk/sync-client           → AgentExchangeClient usage
/docs/sdk/async-client          → AsyncAgentExchangeClient usage
/docs/sdk/websocket-client      → AgentExchangeWS streaming
/docs/sdk/error-handling        → Exception hierarchy
│
/docs/mcp                       → Section: MCP Server
/docs/mcp/overview              → What is MCP, how it works
/docs/mcp/setup                 → Claude Desktop / Cline setup
/docs/mcp/tools                 → All 12 tools reference
│
/docs/frameworks                → Section: Framework Guides
/docs/frameworks/langchain      → LangChain integration
/docs/frameworks/crewai         → CrewAI integration
/docs/frameworks/agent-zero     → Agent Zero integration
/docs/frameworks/openclaw       → OpenClaw integration
│
/docs/backtesting               → Section: Backtesting
/docs/backtesting/overview      → What is backtesting (plain English)
/docs/backtesting/guide         → Technical guide (lifecycle, API, strategies)
/docs/backtesting/strategies    → Strategy examples (MA, RSI, breakout, momentum)
│
/docs/battles                   → Section: Agent Battles
/docs/battles/overview          → What are battles, presets
/docs/battles/lifecycle         → Create → start → monitor → results
/docs/battles/live-monitoring   → WebSocket events, real-time data
/docs/battles/results-replay    → Results, rankings, equity replay
│
/docs/skill-reference           → Full skill.md (downloadable)
```

**Total: ~35 pages** organized in 10 sections.

---

## UI Design Spec

### Layout

```
┌─────────────────────────────────────────────────────┐
│  Header: TradeReady.io logo | Docs | API | SDK      │
│          Search bar (Cmd+K)  | GitHub | Get Started  │
├──────────┬──────────────────────────────────────────┤
│ Sidebar  │  Content Area                             │
│          │                                           │
│ Overview │  # Page Title                             │
│ Quick... │                                           │
│          │  Content with code blocks, tables,        │
│ Concepts │  callouts, tabs (curl/python/sdk),        │
│  ├ How.. │  copy buttons, syntax highlighting        │
│  ├ Agen. │                                           │
│  ├ Trad. │                                           │
│  └ Risk  │                                           │
│          │                          ┌───────────────┐│
│ API      │                          │ On This Page  ││
│  ├ Auth  │                          │ • Section 1   ││
│  ├ Mark. │                          │ • Section 2   ││
│  ├ Trad. │                          │ • Section 3   ││
│  ...     │                          └───────────────┘│
│          │                                           │
│ SDK      │  ← Prev Page    Next Page →               │
│ MCP      │                                           │
│ ...      │                                           │
└──────────┴──────────────────────────────────────────┘
```

### Design Tokens (match landing page)

- **Background:** `hsl(var(--background))` — dark navy
- **Sidebar:** `hsl(var(--card))` with border
- **Accent:** Gold (`hsl(var(--accent))`) for links, active states
- **Code blocks:** Dark with Shiki "github-dark" theme
- **Profit/Loss colors:** Green/Red for API response examples
- **Font:** Inter (body), JetBrains Mono (code)

### Key UI Features

1. **Command-K search** — Orama-powered full-text search across all docs
2. **Code tabs** — Show examples in curl / Python SDK / MCP side by side
3. **Copy button** — On every code block
4. **Breadcrumbs** — Full path navigation
5. **Table of Contents** — Right sidebar, scrollspy highlighting
6. **Previous/Next** — Navigation between pages
7. **Dark/Light mode** — Synced with landing page theme toggle
8. **Mobile responsive** — Hamburger sidebar on mobile
9. **Version badge** — Show API version (v1)
10. **"Try it" links** — Link to Swagger UI for interactive testing

---

## Phase Breakdown

### Phase 1: Setup & Infrastructure (Foundation) ✅ DONE

**Goal:** Fumadocs installed, configured, rendering a basic page at `/docs`.

| # | Task | Details | Status |
|---|------|---------|--------|
| 1.1 | Install Fumadocs packages | `fumadocs-core`, `fumadocs-ui`, `fumadocs-mdx`, `@types/mdx` | ✅ Done |
| 1.2 | Create `source.config.ts` | Fumadocs content source config pointing to `content/docs/` | ✅ Done |
| 1.3 | Update `next.config.ts` | Add `createMDX()` wrapper from fumadocs-mdx | ✅ Done |
| 1.4 | Create docs layout | `Frontend/src/app/docs/layout.tsx` — Fumadocs `DocsLayout` with sidebar config | ✅ Done |
| 1.5 | Create docs catch-all page | `Frontend/src/app/docs/[[...slug]]/page.tsx` — renders MDX content | ✅ Done |
| 1.6 | Create first content file | `Frontend/content/docs/index.mdx` — welcome page | ✅ Done |
| 1.7 | Configure Fumadocs theme | Match TradeReady.io brand colors (dark-first, gold accent) in layout | ✅ Done |
| 1.8 | Verify routing | Ensure `/docs` is public (outside `(dashboard)` route group, no auth middleware) | ✅ Done |
| 1.9 | Test build | `pnpm build` passes with docs route | ✅ Done |

**Notes:**
- Old dashboard `/docs` page moved to `/docs-hub` to avoid route conflict with Fumadocs catch-all
- `source.ts` loader created at `Frontend/src/lib/source.ts`
- Theme CSS overrides at `Frontend/src/app/docs/docs-theme.css` (dark navy + gold accent)
- `RootProvider` wraps docs layout with dark theme default

### Phase 2: Content Migration (Core Docs) ✅ DONE

**Goal:** All existing markdown content migrated to MDX, organized in the sitemap structure.

| # | Task | Details | Status |
|---|------|---------|--------|
| 2.1 | Create content directory structure | `Frontend/content/docs/` with all section folders matching sitemap | ✅ Done |
| 2.2 | Migrate quickstart.md | Convert to MDX with frontmatter (title, description, icon) | ✅ Done |
| 2.3 | Create "Concepts" section | `how-it-works.mdx`, `agents.mdx`, `trading-rules.mdx`, `risk-management.mdx` — extracted from skill.md | ✅ Done |
| 2.4 | Create "API" section | Split `api_reference.md` into per-topic MDX files (auth, market, trading, account, analytics, agents, battles, errors, rate-limits) | ✅ Done |
| 2.5 | Create "WebSocket" section | Extract from skill.md/api_reference.md → `connection.mdx`, `channels.mdx` | ✅ Done |
| 2.6 | Migrate SDK docs | Convert SDK README → `installation.mdx`, `sync-client.mdx`, `async-client.mdx`, `websocket-client.mdx`, `error-handling.mdx` | ✅ Done |
| 2.7 | Migrate MCP docs | Convert `mcp_server.md` → `overview.mdx`, `setup.mdx`, `tools.mdx` | ✅ Done |
| 2.8 | Migrate framework guides | Convert all 4 framework guides to MDX | ✅ Done |
| 2.9 | Migrate backtesting docs | Convert both backtesting guides + extract strategy examples | ✅ Done |
| 2.10 | Create battles section | Extract from skill.md → `overview.mdx`, `lifecycle.mdx`, `live-monitoring.mdx`, `results-replay.mdx` | ✅ Done |
| 2.11 | Create skill reference page | Full skill.md as single MDX page with download button | ✅ Done |
| 2.12 | Configure sidebar navigation | Define `meta.json` files in each content folder for ordering and labels | ✅ Done |

**Notes:**
- 46 files total: 35 MDX pages + 11 meta.json sidebar configs
- All content uses Fumadocs components: `Callout`, `Tab`/`Tabs` for multi-language code examples
- Sidebar navigation configured via `meta.json` in each section folder with proper ordering
- Build passes with zero errors — all 37 doc pages statically generated
- Content sources: `docs/skill.md`, `docs/api_reference.md`, `docs/quickstart.md`, `docs/mcp_server.md`, `docs/backtesting-guide.md`, `docs/backtesting-explained.md`, `docs/framework_guides/*.md`, `sdk/README.md`

### Phase 3: Enhanced UI Components ✅ DONE

**Goal:** Custom MDX components for API docs, code examples, and interactive elements.

| # | Task | Details | Status |
|---|------|---------|--------|
| 3.1 | API endpoint component | `<Endpoint method="GET" path="/market/price/{symbol}" />` — styled method badge + path | ✅ Done |
| 3.2 | Request/Response component | `<ApiExample>` with tabs for curl / Python / SDK, syntax highlighted | ✅ Done |
| 3.3 | Parameter table component | `<ParamTable>` — name, type, required, description columns | ✅ Done |
| 3.4 | Callout components | Info, Warning, Tip, Danger callouts (Fumadocs has built-in, customize styling) | ✅ Done (built-in) |
| 3.5 | Code group component | Tabbed code blocks for multi-language examples | ✅ Done (built-in Tabs) |
| 3.6 | "Try in Swagger" button | Links to `/docs` (Swagger UI) with the right endpoint pre-selected | ✅ Done |
| 3.7 | Response schema component | Collapsible JSON response with field descriptions | ✅ Done |
| 3.8 | Status badge component | For battle states, order statuses, etc. | ✅ Done |

**Notes:**
- 6 custom components created in `Frontend/src/components/docs/`: `Endpoint`, `ApiExample`, `ParamTable`, `SwaggerButton`, `ResponseSchema`, `StatusBadge`
- Tasks 3.4 and 3.5 use Fumadocs built-in `Callout` and `Tab`/`Tabs` components (already in use since Phase 2)
- All 9 API MDX pages + battles overview updated to use the new components
- Components are imported directly in MDX files (same pattern as fumadocs-ui components)
- Build passes with zero errors — all 37 doc pages statically generated

### Phase 4: Search Integration ✅ DONE

**Goal:** Full-text search with Cmd+K shortcut.

| # | Task | Details | Status |
|---|------|---------|--------|
| 4.1 | Install Orama | Fumadocs has built-in search via `fumadocs-core/search/server` (no extra package needed) | ✅ Done |
| 4.2 | Configure search index | `createFromSource(source)` auto-indexes all MDX content at build time | ✅ Done |
| 4.3 | Add search UI | Fumadocs `DocsLayout` includes SearchDialog with Cmd+K trigger; configured via `RootProvider` search options | ✅ Done |
| 4.4 | Test search | Build passes — `/api/search` route registered, all 37 doc pages indexed | ✅ Done |

**Notes:**
- Search API route created at `Frontend/src/app/api/search/route.ts` using `createFromSource` from `fumadocs-core/search/server`
- No additional packages needed — Fumadocs v16 includes built-in search server
- `RootProvider` in `layout.tsx` configured with `search.options.api: "/api/search"`
- Fumadocs `DocsLayout` automatically renders the SearchDialog component with Cmd+K (⌘K) shortcut
- Search indexes all page titles, descriptions, and content (including code blocks)
- Build passes with zero errors — 37 static doc pages + dynamic `/api/search` route

### Phase 5: Landing Page Integration ✅ DONE

**Goal:** Connect docs to the landing page navigation and footer.

| # | Task | Details | Status |
|---|------|---------|--------|
| 5.1 | Add "Docs" to landing header | Add docs link to the glow menu navigation (desktop + mobile) | ✅ Done |
| 5.2 | Update footer links | Replace `#` hrefs with actual `/docs/*` routes in `FOOTER_LINKS` | ✅ Done |
| 5.3 | Add "Read the Docs" CTA | Add a prominent link in the CTA section | ✅ Done |
| 5.4 | Update ROUTES constant | Add docs routes (`docs`, `docsApi`, `docsSdk`, `docsFrameworks`, `docsQuickstart`) to `src/lib/constants.ts` | ✅ Done |
| 5.5 | Deprecate dashboard docs | Added "View Full Docs" banner linking to `/docs` from `/docs-hub`; updated section links to point to real doc pages | ✅ Done |

**Notes:**
- `ROUTES.docs` now points to `/docs` (Fumadocs public docs); `ROUTES.docsHub` points to `/docs-hub` (dashboard hub)
- Dashboard sidebar still links to `/docs-hub` (internal quick-reference hub)
- Landing glow menu has gold-accent "Docs" item with `BookOpen` icon between "Integrations" and "Early Access"
- Mobile nav updated with "Docs" link that navigates to `/docs` route (not anchor scroll)
- Footer "Resources" section: API Docs → `/docs/api`, Python SDK → `/docs/sdk`, Framework Guides → `/docs/frameworks`
- CTA section has "Read the Docs" link with gold accent styling below the waitlist form
- Dashboard docs-hub sections now link to real Fumadocs pages instead of `#` anchors
- Build passes with zero errors — all 37 doc pages + landing page statically generated

### Phase 6: Polish & SEO

**Goal:** Production-ready documentation with SEO, performance, and accessibility.

| # | Task | Details |
|---|------|---------|
| 6.1 | Add OpenGraph metadata | Per-page titles, descriptions for social sharing |
| 6.2 | Generate sitemap | Auto-generate `/docs/sitemap.xml` |
| 6.3 | Add og:image | Create a docs-specific OG image template |
| 6.4 | Test mobile responsiveness | Verify sidebar collapse, code block scroll, search on mobile |
| 6.5 | Test dark/light mode | Ensure all docs components work in both themes |
| 6.6 | Performance audit | Check bundle size impact, lazy loading of docs pages |
| 6.7 | Accessibility audit | ARIA labels, keyboard navigation, screen reader testing |
| 6.8 | Cross-browser test | Chrome, Firefox, Safari, Edge |
| 6.9 | 404 page | Custom docs 404 with search and popular links |
| 6.10 | Analytics | Track page views, search queries (optional, if analytics is set up) |

---

## Content Guidelines

### What to Include (End-User Focus)
- **How to register** and get API keys
- **How to authenticate** (API key vs JWT, when to use which)
- **All public API endpoints** with request/response examples
- **WebSocket protocol** with subscribe/unsubscribe examples
- **Python SDK** with real code examples (sync, async, streaming)
- **MCP Server** setup for Claude Desktop and Cline
- **Framework integrations** (LangChain, CrewAI, etc.)
- **Backtesting** — what it is, how to use it, strategy examples
- **Battles** — what they are, how to create/monitor/view results
- **Trading rules** — fees, slippage, position limits, circuit breaker
- **Error codes** — what each error means and how to handle it
- **Rate limits** — per-endpoint limits and best practices
- **Skill file** — downloadable reference for AI agents

### What to Exclude (Internal Only)
- Database schemas, table definitions, migrations
- Internal service/repository architecture
- Middleware chain, dependency injection patterns
- Docker Compose setup, infrastructure details
- Celery task internals
- CI/CD pipeline configuration
- Internal monitoring (Prometheus, Grafana setup)
- Test infrastructure and fixtures
- Alembic migration commands

### Tone & Style
- **Audience:** Developer building AI trading agents
- **Tone:** Clear, direct, technical but approachable
- **Code examples:** Always show working code, not pseudocode
- **Prefer:** Show don't tell — code examples over long paragraphs
- **Every API page:** Method + path + description + parameters + example request + example response + error cases

---

## File Structure (Final)

```
Frontend/
├── content/
│   └── docs/
│       ├── index.mdx                    # Welcome page
│       ├── quickstart.mdx               # 5-minute quickstart
│       ├── meta.json                    # Root sidebar config
│       ├── concepts/
│       │   ├── meta.json
│       │   ├── how-it-works.mdx
│       │   ├── agents.mdx
│       │   ├── trading-rules.mdx
│       │   └── risk-management.mdx
│       ├── api/
│       │   ├── meta.json
│       │   ├── authentication.mdx
│       │   ├── market-data.mdx
│       │   ├── trading.mdx
│       │   ├── account.mdx
│       │   ├── analytics.mdx
│       │   ├── agents.mdx
│       │   ├── battles.mdx
│       │   ├── errors.mdx
│       │   └── rate-limits.mdx
│       ├── websocket/
│       │   ├── meta.json
│       │   ├── connection.mdx
│       │   └── channels.mdx
│       ├── sdk/
│       │   ├── meta.json
│       │   ├── installation.mdx
│       │   ├── sync-client.mdx
│       │   ├── async-client.mdx
│       │   ├── websocket-client.mdx
│       │   └── error-handling.mdx
│       ├── mcp/
│       │   ├── meta.json
│       │   ├── overview.mdx
│       │   ├── setup.mdx
│       │   └── tools.mdx
│       ├── frameworks/
│       │   ├── meta.json
│       │   ├── langchain.mdx
│       │   ├── crewai.mdx
│       │   ├── agent-zero.mdx
│       │   └── openclaw.mdx
│       ├── backtesting/
│       │   ├── meta.json
│       │   ├── overview.mdx
│       │   ├── guide.mdx
│       │   └── strategies.mdx
│       ├── battles/
│       │   ├── meta.json
│       │   ├── overview.mdx
│       │   ├── lifecycle.mdx
│       │   ├── live-monitoring.mdx
│       │   └── results-replay.mdx
│       └── skill-reference.mdx          # Full skill file
├── src/
│   ├── app/
│   │   └── docs/                        # Public docs route (NO auth)
│   │       ├── layout.tsx               # Fumadocs DocsLayout
│   │       └── [[...slug]]/
│   │           └── page.tsx             # Fumadocs content renderer
│   └── components/
│       └── docs/                        # Custom MDX components
│           ├── endpoint.tsx             # API endpoint badge
│           ├── api-example.tsx          # Tabbed request/response
│           ├── param-table.tsx          # Parameter table
│           └── response-schema.tsx      # Collapsible JSON schema
├── source.config.ts                     # Fumadocs content source
└── next.config.ts                       # Updated with createMDX()
```

---

## Task Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| **Phase 1** | 9 tasks | Setup Fumadocs, routing, theme, first page |
| **Phase 2** | 12 tasks | Migrate all content to MDX (~35 pages) |
| **Phase 3** | 8 tasks | Custom API docs components |
| **Phase 4** | 4 tasks | Full-text search with Orama |
| **Phase 5** | 5 tasks | Landing page integration |
| **Phase 6** | 10 tasks | SEO, polish, accessibility, testing |
| **Total** | **48 tasks** | |

### Priority Order

1. **Phase 1** → Must be done first (infrastructure)
2. **Phase 2** → Core value (content)
3. **Phase 5** → Connect to landing page (discoverability)
4. **Phase 4** → Search (usability)
5. **Phase 3** → Enhanced components (polish)
6. **Phase 6** → SEO & final polish

### Dependencies

```
Phase 1 (setup) ──→ Phase 2 (content) ──→ Phase 5 (landing integration)
                         │
                         ├──→ Phase 3 (components) ──→ Phase 6 (polish)
                         │
                         └──→ Phase 4 (search)
```

Phase 3, 4, and 5 can run in parallel after Phase 2 is complete.
