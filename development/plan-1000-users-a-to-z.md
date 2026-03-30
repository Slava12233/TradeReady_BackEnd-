---
type: plan
tags:
  - external-agents
  - growth
  - free-tier
  - infrastructure
  - launch
date: 2026-03-23
status: active
---

# A-Z Plan: Launch TradeReady to 1,000 External AI Agent Users

## Current State Summary

**What's WORKING:** Core trading (600+ pairs), backtesting, battles, strategies, MCP server (58 tools), Python SDK, WebSocket streaming, multi-agent isolation, risk management, monitoring, documentation (50+ docs pages).

**What's BLOCKING public launch:** No HTTPS, no per-user quotas, no email verification, CORS locked to localhost, leaderboard ROI returns 0, auth endpoints skip rate limiting, no starting_balance cap, no legal pages.

---

## Phase 0: Critical Security & Infrastructure (Week 1)
> **Goal:** Make the platform safe for external traffic

### Module 0.1: HTTPS / Reverse Proxy
**Files to create/modify:**
- `nginx/nginx.conf` — NEW
- `nginx/ssl/` — certificates directory
- `docker-compose.yml` — add nginx service
- `docker-compose.prod.yml` — NEW production overrides

**Tasks:**
1. Add nginx service to Docker Compose with TLS termination (Let's Encrypt / Caddy)
2. Route all traffic through nginx → api:8000
3. Add HTTPS redirect (80 → 443)
4. Add WebSocket proxy pass (`/ws/v1` → upstream)
5. Remove direct port 8000 exposure from API container
6. Remove pgAdmin port 5050 exposure (or add basic auth)
7. Remove TimescaleDB port 5432 exposure (internal only)

**Acceptance:** `curl https://api.yourdomain.com/health` returns 200 over TLS.

---

### Module 0.2: CORS Configuration
**Files to modify:**
- `src/main.py` — externalize `allow_origins` to env var
- `src/config.py` — add `CORS_ORIGINS` setting
- `.env.example` — document CORS_ORIGINS

**Tasks:**
1. Move hardcoded `localhost:3000/3001` origins to `CORS_ORIGINS` env var (comma-separated)
2. Add production domain to allowed origins
3. Keep `allow_credentials=True` with explicit origins (never wildcard)

**Acceptance:** Frontend at `https://app.yourdomain.com` can call API without CORS errors.

---

### Module 0.3: Auth Endpoint Rate Limiting
**Files to modify:**
- `src/api/middleware/rate_limit.py` — remove `/api/v1/auth/` from `_PUBLIC_PREFIXES`

**Tasks:**
1. Remove `/api/v1/auth/` from the bypass list in rate_limit.py
2. Add a separate `auth` tier: 20 requests/min per IP (not per API key, since auth endpoints don't have one yet)
3. Use IP-based rate limiting for unauthenticated endpoints: `rate_limit:ip:{ip}:{endpoint}:{minute}`
4. Add login brute-force protection: after 10 failed attempts in 15 min, lock IP for 30 min

**Acceptance:** `ab -n 100 -c 10 POST /api/v1/auth/register` → returns 429 after 20 requests.

---

### Module 0.4: Registration Hardening
**Files to modify:**
- `src/api/routes/auth.py` — add starting_balance cap, email required
- `src/api/schemas/auth.py` — tighten validation

**Tasks:**
1. Cap `starting_balance` at 100,000 USDT (server-side max, env-configurable)
2. Make `email` required (not optional) for registration
3. Make `password` required with min 8 chars (already exists, verify)
4. Add password strength: require at least 1 digit + 1 letter
5. Add display_name uniqueness check (prevent impersonation)
6. Return sanitized response (never leak internal IDs unnecessarily)

**Acceptance:** Registration with `starting_balance: 999999999` returns 422.

---

### Module 0.5: Production Deployment Config
**Files to create/modify:**
- `docker-compose.prod.yml` — NEW production overrides
- `.env.production.example` — NEW template

**Tasks:**
1. Create production compose file that:
   - Disables pgAdmin entirely
   - Sets all DB/Redis ports to internal-only
   - Sets resource limits appropriate for 16 CPU / 32 GB RAM server
   - Enables JSON structured logging
   - Sets `PYTHONOPTIMIZE=1`
2. Document the production deployment process
3. Set up server (Hetzner/OVH/Contabo: 16 CPU, 32 GB RAM, 500 GB NVMe)
4. Configure DNS: `api.yourdomain.com`, `app.yourdomain.com`
5. Deploy with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

**Acceptance:** Platform running at public URL with HTTPS, no debug ports exposed.

---

## Phase 1: Per-User Resource Limits & Quotas (Week 1-2)
> **Goal:** Prevent any single user from exhausting the platform

### Module 1.1: Account Tier Model
**Files to modify:**
- `src/database/models.py` — add `tier` field to Account
- `alembic/versions/` — NEW migration

**Tasks:**
1. Add `tier` column to `accounts` table: `VARCHAR(20)` CHECK IN (`free`, `pro`, `enterprise`), default `free`
2. Add `tier_limits` JSONB column with defaults per tier
3. Create migration (non-destructive: adds nullable column, then backfills `free`, then sets NOT NULL)

**Default tier limits:**
```json
{
  "free": {
    "max_agents": 5,
    "max_backtests_per_day": 10,
    "max_concurrent_backtests": 1,
    "max_backtest_days": 30,
    "max_battles_per_day": 2,
    "max_active_battles": 1,
    "max_strategy_tests_per_day": 3,
    "max_websocket_subscriptions": 5,
    "max_starting_balance": 100000,
    "data_retention_days": 30
  },
  "pro": {
    "max_agents": 25,
    "max_backtests_per_day": 100,
    "max_concurrent_backtests": 5,
    "max_backtest_days": 365,
    "max_battles_per_day": 10,
    "max_active_battles": 3,
    "max_strategy_tests_per_day": 30,
    "max_websocket_subscriptions": 20,
    "max_starting_balance": 1000000,
    "data_retention_days": 365
  }
}
```

**Acceptance:** `SELECT tier FROM accounts WHERE id = ?` returns `free` for all existing accounts.

---

### Module 1.2: Quota Tracking Service
**Files to create:**
- `src/quotas/` — NEW module
  - `src/quotas/__init__.py`
  - `src/quotas/service.py` — QuotaService class
  - `src/quotas/limits.py` — tier limit definitions
  - `src/quotas/CLAUDE.md` — module docs

**Tasks:**
1. `QuotaService` with methods:
   - `check_agent_limit(account_id) → bool` — count agents vs tier max
   - `check_backtest_limit(account_id) → bool` — count today's backtests vs tier max
   - `check_battle_limit(account_id) → bool` — count today's battles vs tier max
   - `check_strategy_test_limit(account_id) → bool` — count today's test runs vs tier max
   - `get_usage(account_id) → UsageReport` — current usage vs limits
   - `increment_usage(account_id, resource: str)` — Redis INCR with daily expiry
2. Use Redis for daily counters: `quota:{account_id}:{resource}:{date}` with EXPIRE at midnight UTC
3. Counters increment on successful resource creation (not on attempt)

**Acceptance:** After 10 backtests, 11th attempt returns 403 with `{"error": {"code": "quota_exceeded", "message": "Free tier limit: 10 backtests/day", "upgrade_url": "/pricing"}}`.

---

### Module 1.3: Quota Enforcement in Routes
**Files to modify:**
- `src/api/routes/agents.py` — enforce max_agents on POST
- `src/api/routes/backtest.py` — enforce backtest limits on POST /create
- `src/api/routes/battles.py` — enforce battle limits on POST
- `src/api/routes/strategies.py` — enforce test run limits on POST /test
- `src/api/routes/account.py` — enforce starting_balance cap
- `src/dependencies.py` — add QuotaServiceDep

**Tasks:**
1. Add `QuotaServiceDep` to `src/dependencies.py`
2. Before creating an agent: `if not quota.check_agent_limit(account_id): raise QuotaExceededError("agents")`
3. Before creating a backtest: `if not quota.check_backtest_limit(account_id): raise QuotaExceededError("backtests")`
4. Before creating a battle: `if not quota.check_battle_limit(account_id): raise QuotaExceededError("battles")`
5. Before running strategy test: `if not quota.check_strategy_test_limit(account_id): raise QuotaExceededError("strategy_tests")`
6. Cap WebSocket subscriptions per connection (already 10, lower to 5 for free tier)

**Acceptance:** Free tier user creating 6th agent gets 403 with clear error message.

---

### Module 1.4: Usage API Endpoint
**Files to modify:**
- `src/api/routes/account.py` — add GET /account/usage

**Tasks:**
1. `GET /api/v1/account/usage` returns:
```json
{
  "tier": "free",
  "usage": {
    "agents": { "used": 3, "limit": 5 },
    "backtests_today": { "used": 7, "limit": 10 },
    "battles_today": { "used": 1, "limit": 2 },
    "strategy_tests_today": { "used": 0, "limit": 3 }
  },
  "resets_at": "2026-03-24T00:00:00Z"
}
```
2. Add MCP tool: `get_usage` — so agents can check their own limits

**Acceptance:** SDK call `client.get_usage()` returns tier info and current counts.

---

## Phase 2: Fix Critical Features (Week 2)
> **Goal:** Make leaderboard, battles, and profiles actually work

### Module 2.1: Fix Leaderboard ROI Calculation
**Files to modify:**
- `src/api/routes/analytics.py` — fix `_compute_roi()` function

**Tasks:**
1. Replace the placeholder `return Decimal("0")` with actual ROI calculation
2. Formula: `roi = (current_equity - starting_balance) / starting_balance * 100`
3. Get `current_equity` from `PortfolioTracker` (sum of balances + unrealized PnL)
4. Get `starting_balance` from agent/account `starting_balance` field
5. Add caching (Redis, 60s TTL) since leaderboard is expensive to compute
6. Make leaderboard agent-scoped (rank individual agents, not accounts)
7. Add `agent_display_name`, `framework`, `llm_model` to leaderboard entries

**Acceptance:** Leaderboard returns non-zero ROI values, sorted correctly.

---

### Module 2.2: Public Leaderboard (No Auth Required)
**Files to modify:**
- `src/api/routes/analytics.py` — add public leaderboard endpoint

**Tasks:**
1. Add `GET /api/v1/public/leaderboard` — no auth required
2. Returns top 50 agents: `display_name`, `roi_pct`, `sharpe_ratio`, `win_rate`, `total_trades`, `framework`, `llm_model`
3. Does NOT expose: API keys, account IDs, internal agent IDs, balance amounts
4. Add to CORS: public endpoints accessible from any origin
5. Cache aggressively: 5-minute TTL

**Acceptance:** `curl https://api.yourdomain.com/api/v1/public/leaderboard` returns rankings without auth.

---

### Module 2.3: Public Agent Profiles
**Files to create/modify:**
- `src/api/routes/public.py` — NEW public routes module

**Tasks:**
1. `GET /api/v1/public/agents/{id}/profile` — no auth required
2. Returns: `display_name`, `framework`, `llm_model`, `strategy_tags`, `created_at`, `roi_pct`, `sharpe_ratio`, `win_rate`, `total_trades`, `max_drawdown`, `equity_curve` (last 30 days, sampled daily)
3. Does NOT expose: API key, risk_profile internals, raw trade data
4. Agents can opt-out via `public_profile: false` field (default: true)
5. Add shareable URL: `https://app.yourdomain.com/agent/{id}`

**Acceptance:** Shareable agent profile URL shows performance card without login.

---

### Module 2.4: Platform-Wide Stats (Landing Page Data)
**Files to create/modify:**
- `src/api/routes/public.py` — add stats endpoint

**Tasks:**
1. `GET /api/v1/public/stats` — no auth required
2. Returns:
```json
{
  "total_agents": 1247,
  "total_trades_24h": 85420,
  "total_strategies": 3210,
  "active_battles": 12,
  "top_roi_24h": "14.7%",
  "pairs_available": 623,
  "frameworks": {"langchain": 312, "agent-zero": 189, "openclaw": 95, ...}
}
```
3. Cache for 5 minutes
4. Use for landing page social proof

**Acceptance:** Landing page shows live platform stats.

---

## Phase 3: Onboarding & Developer Experience (Week 2-3)
> **Goal:** Time-to-first-trade under 5 minutes

### Module 3.1: Streamlined Registration + Auto Agent Creation
**Files to modify:**
- `src/api/routes/auth.py` — auto-create first agent on registration
- `src/accounts/service.py` — enhance registration flow

**Tasks:**
1. On registration, auto-create a default agent named "{display_name}'s Agent"
2. Return both account credentials AND agent API key in registration response:
```json
{
  "account_id": "...",
  "api_key": "ak_live_account_...",
  "api_secret": "sk_live_...",
  "agent": {
    "agent_id": "...",
    "agent_api_key": "ak_live_agent_...",
    "display_name": "MyBot's Agent"
  }
}
```
3. This removes the extra step of creating an agent after registration
4. User can create more agents later (up to tier limit)

**Acceptance:** Single POST to `/register` returns a working agent API key.

---

### Module 3.2: Quick Start Integration Configs
**Files to create:**
- `docs/integrations/` — framework-specific guides (already partially exists)
- `src/api/routes/public.py` — add config generator endpoint

**Tasks:**
1. `GET /api/v1/agents/{id}/mcp-config` — returns ready-to-paste MCP config JSON:
```json
{
  "mcpServers": {
    "tradeready": {
      "command": "python",
      "args": ["-m", "src.mcp.server"],
      "env": {
        "MCP_API_KEY": "ak_live_your_key_here",
        "API_BASE_URL": "https://api.tradeready.com"
      }
    }
  }
}
```
2. `GET /api/v1/agents/{id}/sdk-snippet` — returns Python quickstart code
3. `GET /api/v1/agents/{id}/curl-snippet` — returns curl example with agent's key
4. Add "Copy Config" button in frontend agent detail page
5. Ensure all 4 framework guides (LangChain, CrewAI, Agent Zero, OpenClaw) are current

**Acceptance:** User copies MCP config from dashboard → pastes into Claude Desktop → trades within 60 seconds.

---

### Module 3.3: Frontend Onboarding Wizard Enhancement
**Files to modify:**
- `Frontend/src/components/setup/` — enhance wizard steps

**Tasks:**
1. After account creation, wizard shows:
   - Step 1: "Your agent is ready" + API key (copy button)
   - Step 2: "Choose your framework" → shows config for MCP / SDK / REST
   - Step 3: "Make your first trade" → interactive demo (prefilled curl/code)
   - Step 4: "Explore" → links to backtest, strategies, battles
2. Add "Quick Actions" to dashboard: "Run Backtest", "Create Strategy", "Start Battle"
3. Show empty-state messages with CTAs: "No trades yet → Connect your agent"

**Acceptance:** New user completes wizard in under 3 minutes, understands next steps.

---

### Module 3.4: Publish SDK to PyPI
**Files to modify:**
- `sdk/pyproject.toml` — finalize metadata
- `sdk/README.md` — create with quickstart examples
- `.github/workflows/publish-sdk.yml` — NEW CI workflow

**Tasks:**
1. Finalize package metadata (description, URLs, classifiers)
2. Write README with:
   - Installation: `pip install agentexchange`
   - 5-line quickstart
   - Link to full docs
3. Add basic SDK tests (at least smoke tests for import, client init)
4. Set up PyPI publishing via GitHub Actions
5. Publish v0.1.0 to PyPI

**Acceptance:** `pip install agentexchange` works from any machine.

---

### Module 3.5: MCP Server as Installable Package
**Files to create:**
- `src/mcp/pyproject.toml` — or ship via npm for Claude Desktop users
- Alternatively: publish Docker image for MCP server

**Tasks:**
1. Option A: Publish MCP server as standalone pip package (`pip install tradeready-mcp`)
2. Option B: Provide a Docker image (`docker run -e MCP_API_KEY=... tradeready/mcp-server`)
3. Option C: Host a remote MCP endpoint (SSE transport instead of stdio) — future
4. For now: document the `pip install -e .` path clearly, or bundle MCP in the SDK

**Acceptance:** External user can run MCP server without cloning the full repo.

---

## Phase 4: Legal, Email & Account Management (Week 2-3)
> **Goal:** Legally operable platform with basic account lifecycle

### Module 4.1: Terms of Service & Privacy Policy
**Files to create:**
- `Frontend/src/app/(public)/terms/page.tsx` — Terms of Service page
- `Frontend/src/app/(public)/privacy/page.tsx` — Privacy Policy page
- `Frontend/src/content/legal/terms.md` — Terms content
- `Frontend/src/content/legal/privacy.md` — Privacy content

**Tasks:**
1. Draft Terms of Service covering:
   - Platform is for simulated trading only, not financial advice
   - User data (trades, strategies) used to improve platform intelligence (the data flywheel)
   - No guarantee of uptime or accuracy
   - Users responsible for their own agent behavior
   - Right to suspend/terminate accounts
   - Limitation of liability
2. Draft Privacy Policy covering:
   - What data we collect (registration info, trading data, agent metadata)
   - How we use it (platform improvement, aggregate analytics)
   - No selling of individual user data
   - Data retention (30 days free tier, configurable)
   - Right to request data deletion
   - Cookie policy (minimal — auth tokens only)
3. Add consent checkbox to registration: "I agree to Terms of Service and Privacy Policy"
4. Store consent timestamp in database

**Acceptance:** `/terms` and `/privacy` pages accessible without login.

---

### Module 4.2: Email Verification
**Files to create:**
- `src/email/` — NEW module
  - `src/email/__init__.py`
  - `src/email/service.py` — EmailService (SMTP or Resend/SendGrid)
  - `src/email/templates.py` — HTML email templates
  - `src/email/CLAUDE.md` — module docs
- `src/database/models.py` — add `email_verified` to Account
- `alembic/versions/` — NEW migration

**Tasks:**
1. Add `email_verified: bool = False` and `verification_token: str | None` to Account model
2. On registration:
   - Generate random verification token
   - Send email with verification link: `https://app.yourdomain.com/verify?token=xxx`
   - Account is `active` but mark `email_verified = False`
3. `GET /api/v1/auth/verify-email?token=xxx` → sets `email_verified = True`
4. Allow trading without verification for 24 hours (grace period for onboarding speed)
5. After 24 hours, restrict to read-only if not verified
6. Use Resend (cheapest: 3,000 emails/month free) or SMTP relay

**Decision point:** Do NOT block registration on email verification — it kills onboarding speed. Grace period is the right tradeoff.

**Acceptance:** User registers → receives email → clicks link → `email_verified` = true.

---

### Module 4.3: Password Reset
**Files to modify:**
- `src/api/routes/auth.py` — add reset endpoints
- `src/email/templates.py` — reset email template

**Tasks:**
1. `POST /api/v1/auth/forgot-password` — accepts email, sends reset link
2. Generate time-limited token (1 hour expiry), store hash in Redis
3. `POST /api/v1/auth/reset-password` — accepts token + new password
4. Invalidate all existing sessions (JWT) on password reset
5. Rate limit: max 3 reset requests per email per hour

**Acceptance:** User resets password via email link, can log in with new password.

---

### Module 4.4: Account Deletion
**Files to modify:**
- `src/api/routes/account.py` — add DELETE endpoint
- `src/accounts/service.py` — cascade delete logic

**Tasks:**
1. `DELETE /api/v1/account` — requires password confirmation
2. Cascade delete all data:
   - Archive agents (set status = 'archived')
   - Delete all balances, orders, trades, positions
   - Delete all backtests and results
   - Delete all strategy definitions
   - Anonymize account (replace email/name with `deleted_{id}`)
   - Keep anonymized trade data for aggregate learning (per privacy policy)
3. Set account status to `deleted`
4. Send confirmation email
5. 30-day soft-delete grace period (can recover if they change their mind)

**Acceptance:** Deleted account cannot log in, all personal data removed.

---

## Phase 5: Frontend Production Deployment (Week 3)
> **Goal:** Frontend accessible at public URL

### Module 5.1: Frontend Production Build
**Files to modify:**
- `Frontend/.env.production` — production env vars
- `Frontend/next.config.ts` — production optimizations
- `docker-compose.prod.yml` — add frontend service

**Tasks:**
1. Set `NEXT_PUBLIC_API_BASE_URL=https://api.yourdomain.com`
2. Set `NEXT_PUBLIC_WS_URL=wss://api.yourdomain.com/ws/v1`
3. Add frontend to Docker Compose (multi-stage build: deps → build → serve with standalone output)
4. Configure nginx to serve frontend at `app.yourdomain.com` and proxy `/api` to backend
5. Enable Next.js `output: "standalone"` for Docker
6. Add healthcheck for frontend container

**Acceptance:** `https://app.yourdomain.com` loads the platform with working API connection.

---

### Module 5.2: Landing Page Update
**Files to modify:**
- `Frontend/src/app/page.tsx` — update from "Coming Soon" to live landing
- `Frontend/src/components/landing/` — enhance with live stats

**Tasks:**
1. Replace "Coming Soon" with active landing page:
   - Hero: "Test Your AI Trading Agent on 600+ Real Crypto Pairs — Free"
   - Live stats widget (from `GET /public/stats`)
   - Framework logos (OpenClaw, Agent Zero, LangChain, CrewAI, Claude)
   - "Get Started in 5 Minutes" CTA → `/register`
   - Live leaderboard preview (top 10 from `/public/leaderboard`)
2. Add SEO meta tags, OpenGraph images
3. Add Google Analytics / PostHog for conversion tracking

**Acceptance:** Landing page shows live platform stats and converts visitors to registrations.

---

### Module 5.3: Public Pages (No Auth)
**Files to create:**
- `Frontend/src/app/(public)/leaderboard/page.tsx` — public leaderboard
- `Frontend/src/app/(public)/agent/[id]/page.tsx` — public agent profile
- `Frontend/src/app/(public)/battles/page.tsx` — public battle viewer

**Tasks:**
1. Public leaderboard page with sorting, filtering, time periods
2. Public agent profile with equity curve, stats, badges
3. Public battle viewer — watch active battles in real-time
4. All pages have "Sign Up Free" CTA for non-authenticated visitors
5. SEO-friendly: server-side rendered, proper meta tags

**Acceptance:** Non-logged-in user can view leaderboard, agent profiles, and active battles.

---

## Phase 6: Data Learning Pipeline (Week 3-4)
> **Goal:** Our internal agents learn from user trading data

### Module 6.1: Aggregate Data Pipeline
**Files to create:**
- `src/tasks/data_aggregation.py` — NEW Celery tasks
- `src/analytics/aggregate.py` — NEW aggregation logic

**Tasks:**
1. Daily Celery task: aggregate cross-agent trading patterns
2. Compute:
   - Top performing symbol/timeframe combinations
   - Most successful entry/exit condition patterns from strategy definitions
   - Risk profile correlations with performance (what limits lead to best Sharpe?)
   - Framework effectiveness: which LLM models / agent frameworks perform best?
   - Regime detection: when do most agents switch from bullish to bearish?
3. Store aggregates in `platform_insights` table (NEW)
4. Feed into internal agent retraining pipeline (`agent/strategies/`)

**Acceptance:** Daily report shows top strategies, best-performing frameworks, market regime consensus.

---

### Module 6.2: Internal Agent Learning Bridge
**Files to modify:**
- `agent/strategies/ensemble/attribution.py` — add cross-agent learning
- `agent/strategies/evolutionary/evolve.py` — seed from top user strategies
- `agent/strategies/regime/` — use aggregate regime signals

**Tasks:**
1. **Genetic Algorithm seeding:** When evolving new populations, include top 5 user strategy definitions (anonymized) as seed genomes
2. **Ensemble weighting:** Use battle results to inform strategy weight allocation — strategies that win battles get higher weights
3. **Regime detection:** Aggregate agent behavior (when 70%+ agents reduce position sizes simultaneously) as a regime change signal
4. **Risk calibration:** Use aggregate drawdown data to tune `DynamicSizer` parameters
5. All learning uses aggregate/anonymized data only — never individual user strategies directly

**Acceptance:** Internal agent retraining cycle incorporates aggregate user data.

---

### Module 6.3: Privacy-Safe Data Extraction
**Files to create:**
- `src/analytics/privacy.py` — anonymization utilities

**Tasks:**
1. k-anonymity: only aggregate data from groups of 10+ agents
2. Strategy definitions: extract parameter distributions, not individual configs
3. Never expose which specific user's strategy contributed to learning
4. Configurable opt-out: `Account.data_sharing_opt_out: bool = False`
5. Opted-out accounts excluded from all aggregation queries

**Acceptance:** Opt-out accounts are invisible to the aggregation pipeline.

---

## Phase 7: Community & Viral Features (Week 4-5)
> **Goal:** Create engagement loops that drive organic growth

### Module 7.1: Battle Tournament System
**Files to create:**
- `src/tournaments/` — NEW module
  - `src/tournaments/models.py` — Tournament, TournamentRound models
  - `src/tournaments/service.py` — TournamentService
  - `src/tournaments/scheduler.py` — Celery tasks for auto-tournaments
- `src/api/routes/tournaments.py` — NEW routes
- `alembic/versions/` — NEW migration

**Tasks:**
1. Tournament model: `name`, `start_time`, `end_time`, `battle_preset`, `max_participants`, `status`
2. Weekly automated tournaments:
   - Monday: "Sprint Challenge" (1-hour quick battles)
   - Wednesday: "Strategy Showdown" (historical week replay)
   - Friday: "Survival Marathon" (24-hour endurance)
3. Open enrollment: any agent can join (free tier included)
4. Bracket system: round-robin or elimination (configurable)
5. Results page with rankings, replays, stats
6. Public tournament pages (no auth to view)

**Acceptance:** Weekly tournaments auto-run with enrolled agents, results visible publicly.

---

### Module 7.2: Achievement / Badge System
**Files to create:**
- `src/achievements/` — NEW module
  - `src/achievements/models.py` — Achievement, AgentAchievement
  - `src/achievements/checker.py` — achievement evaluation logic
  - `src/achievements/definitions.py` — all achievement definitions
- `alembic/versions/` — NEW migration

**Tasks:**
1. Define achievements:
   - "First Blood" — first profitable trade
   - "Century Club" — 100 trades executed
   - "Sharp Shooter" — Sharpe ratio > 2.0
   - "Battle Royale" — win a battle
   - "Backtester" — complete 10 backtests
   - "Strategy Architect" — create 5 strategies
   - "Top 10" — reach leaderboard top 10
   - "Survivor" — trade for 7 consecutive days
   - "Multi-Agent" — create 3+ agents
   - "Framework Pioneer" — first agent of a new framework type
2. Check achievements after relevant events (trade fill, battle complete, etc.)
3. Display badges on public agent profiles
4. Announce new achievements via WebSocket

**Acceptance:** Agent profile shows earned badges, new achievements trigger notification.

---

### Module 7.3: Social Sharing
**Files to create/modify:**
- `Frontend/src/components/shared/share-card.tsx` — shareable performance cards
- `src/api/routes/public.py` — add OG image generation endpoint

**Tasks:**
1. Generate OG (OpenGraph) images for:
   - Agent profiles: equity curve + stats overlay
   - Battle results: winner card with vs. comparison
   - Leaderboard position: rank card
2. "Share to Twitter/X" button with pre-filled text:
   - "My AI agent ranked #7 on TradeReady with 12.3% ROI this week 🤖📈 [link]"
3. Copy-shareable link for Discord/Slack
4. Embed code for blog posts

**Acceptance:** Sharing a link to Twitter renders a rich card with agent stats.

---

## Phase 8: Monitoring & Operations (Week 4-5)
> **Goal:** Operate the platform reliably at scale

### Module 8.1: Admin Dashboard
**Files to create:**
- `src/api/routes/admin.py` — NEW admin routes (JWT + admin role required)
- `Frontend/src/app/(admin)/` — NEW admin pages

**Tasks:**
1. Admin endpoints (requires new `is_admin` flag on Account):
   - `GET /admin/accounts` — list all accounts with usage stats
   - `POST /admin/accounts/{id}/suspend` — suspend abusive account
   - `POST /admin/accounts/{id}/unsuspend` — reinstate
   - `GET /admin/stats` — platform metrics (users, agents, trades, load)
   - `GET /admin/quotas` — resource utilization breakdown
2. Admin dashboard pages:
   - User list with search, filter by tier
   - Usage heatmap (who's using the most resources)
   - Recent registrations
   - Alert feed (from Prometheus)

**Acceptance:** Admin can view all users, suspend abusive accounts, see platform health.

---

### Module 8.2: Alerting & Notifications
**Files to modify:**
- `monitoring/prometheus/alerts.yml` — add platform alerts
- `docker-compose.prod.yml` — add Alertmanager service

**Tasks:**
1. Add Alertmanager to production stack
2. Configure notification channels: email, Slack (or Discord)
3. Platform-specific alerts:
   - API error rate > 5% for 5 minutes
   - Database connection pool > 80% utilization
   - Redis memory > 80%
   - Disk usage > 80%
   - New registrations > 100/hour (possible bot attack)
   - Single user > 50% of all API calls (abuse)
4. Daily summary email: registrations, active users, trades, system health

**Acceptance:** Alert fires when error rate spikes, notification arrives in Slack/email.

---

### Module 8.3: Database Backup & Recovery
**Tasks:**
1. Configure TimescaleDB continuous backups:
   - Full backup: daily at 03:00 UTC
   - WAL archiving: continuous (point-in-time recovery)
   - Retention: 7 daily + 4 weekly backups
2. Store backups in object storage (S3/Backblaze B2 — ~$5/month for 100 GB)
3. Test restore procedure monthly
4. Document RTO (< 1 hour) and RPO (< 15 minutes) targets

**Acceptance:** Can restore platform from backup within 1 hour.

---

### Module 8.4: Enhanced Data Retention Cleanup
**Files to modify:**
- `src/tasks/cleanup.py` — add tier-aware retention

**Tasks:**
1. Free tier: delete trade history > 30 days, delete backtest results > 30 days
2. Pro tier: keep 1 year
3. Delete inactive accounts (no login + no API call for 90 days) — archive first, delete after 30 more days
4. Prune tick hypertable: keep raw ticks for 7 days, rely on candle aggregates after
5. Add cleanup metrics to Prometheus: rows deleted, storage reclaimed

**Acceptance:** Database growth rate stays linear even as user count grows.

---

## Phase 9: Growth & Marketing (Week 5-8)
> **Goal:** Go from 0 to 1,000 users

### Module 9.1: Launch Preparation
**Tasks:**
1. Create GitHub repository for SDK (public)
2. Write 3 blog posts:
   - "Introducing TradeReady: The AI Agent Trading Gymnasium"
   - "Connect Your AI Agent to 600+ Crypto Pairs in 5 Minutes"
   - "Agent vs Agent: How AI Battles Work on TradeReady"
3. Record demo video: registration → first trade → backtest → battle (under 5 min)
4. Prepare social posts for launch week (Twitter/X, Reddit, Discord)
5. Set up analytics: PostHog or Mixpanel for user tracking

---

### Module 9.2: Community Seeding (Week 5-6, Target: 50 Users)
**Tasks:**
1. Post in AI agent communities:
   - OpenClaw Discord/GitHub
   - Agent Zero community
   - LangChain Discord (#showcase)
   - CrewAI Discord
   - AutoGPT community
   - r/LocalLLaMA, r/MachineLearning, r/algotrading
   - AI Twitter/X (tag framework authors)
2. Create integration examples:
   - OpenClaw config file with TradeReady MCP
   - LangChain tool wrapper for TradeReady SDK
   - Agent Zero tool definition for TradeReady
3. Offer first 50 users "Founder" badge (permanent leaderboard flair)

---

### Module 9.3: Content Marketing (Week 6-8, Target: 200 Users)
**Tasks:**
1. Weekly blog posts:
   - "This Week on TradeReady" — top agents, interesting strategies, battle results
   - Framework-specific tutorials
   - "Strategy Spotlight" — anonymized analysis of top-performing strategies
2. YouTube content:
   - "I pit GPT-4 vs Claude in a crypto trading battle" (viral potential)
   - "Building a trading agent from scratch with LangChain + TradeReady"
   - "My AI agent's first $1,000 in virtual profits"
3. GitHub presence:
   - Example agents repository
   - Integration templates for each framework
   - Open-source the SDK

---

### Module 9.4: Hackathon & Partnership Strategy (Week 7-10, Target: 500 Users)
**Tasks:**
1. Sponsor AI hackathons: provide free platform access + dedicated support
2. Partner with AI bootcamps: "Build a trading agent" as course project
3. Reach out to YouTube creators in AI/trading space
4. Cross-promote with exchange referral programs (when users graduate to real trading)

---

### Module 9.5: Viral Mechanics (Week 8+, Target: 1,000 Users)
**Tasks:**
1. Weekly tournament results auto-posted to Twitter
2. "Challenge" system: agents can challenge each other to battles
3. Referral system: invite friends → both get +1 agent slot
4. Leaderboard seasons: monthly resets with hall of fame
5. "Strategy of the Month" featured on landing page

---

## Phase 10: Premium Tier & Revenue (Week 8-12)
> **Goal:** Monetize power users while keeping free tier generous

### Module 10.1: Stripe Integration
**Files to create:**
- `src/billing/` — NEW module
  - `src/billing/service.py` — StripeService
  - `src/billing/webhooks.py` — Stripe webhook handlers
  - `src/billing/CLAUDE.md` — module docs
- `src/api/routes/billing.py` — billing endpoints

**Tasks:**
1. Stripe Checkout integration for Pro tier ($29/month)
2. `POST /api/v1/billing/checkout` → returns Stripe Checkout URL
3. `POST /api/v1/billing/webhook` → handle payment events
4. On successful payment: update `account.tier` to `pro`
5. On payment failure/cancellation: grace period (7 days), then downgrade to free
6. Customer portal for subscription management

**Acceptance:** User upgrades to Pro, gets higher limits immediately.

---

### Module 10.2: Upgrade Prompts
**Files to modify:**
- Frontend quota exceeded modals
- API error responses for quota_exceeded

**Tasks:**
1. When free tier limit hit, show:
   - What limit was reached
   - Current vs Pro tier comparison
   - "Upgrade to Pro" button → Stripe Checkout
2. Dashboard usage meter showing % of free tier consumed
3. Email at 80% of daily quota: "You're almost at your limit today"

**Acceptance:** User hits limit → sees clear upgrade path → can upgrade in 2 clicks.

---

## Execution Timeline Summary

```
Week 1:  Phase 0 (Security) + Phase 1 (Quotas)
Week 2:  Phase 2 (Fix Features) + Phase 3 (Onboarding) + Phase 4 (Legal/Email)
Week 3:  Phase 4 (continued) + Phase 5 (Frontend Deploy)
Week 4:  Phase 6 (Data Pipeline) + Phase 7 (Community Features)
Week 5:  Phase 8 (Operations) + Phase 9.1-9.2 (Launch Prep + Seed)
Week 6-8:  Phase 9.3-9.4 (Content + Partnerships)
Week 8-12: Phase 9.5 (Viral) + Phase 10 (Premium Tier)
```

## Module Dependency Graph

```
Phase 0 (Security) ──────────┐
                              ▼
Phase 1 (Quotas) ────────► Phase 3 (Onboarding)
                              │
Phase 2 (Fix Features) ──────┤
                              ▼
Phase 4 (Legal/Email) ───► Phase 5 (Frontend Deploy)
                              │
                              ▼
                   Phase 6 (Data Pipeline)
                              │
Phase 7 (Community) ◄────────┤
                              │
Phase 8 (Operations) ◄───────┘
                              │
                              ▼
                   Phase 9 (Growth/Marketing)
                              │
                              ▼
                   Phase 10 (Premium/Revenue)
```

## Resource Estimate

| Phase | Backend Hours | Frontend Hours | DevOps Hours | Total |
|-------|--------------|----------------|--------------|-------|
| Phase 0 | 4 | 0 | 8 | 12 |
| Phase 1 | 12 | 2 | 0 | 14 |
| Phase 2 | 8 | 4 | 0 | 12 |
| Phase 3 | 6 | 8 | 2 | 16 |
| Phase 4 | 10 | 4 | 0 | 14 |
| Phase 5 | 0 | 8 | 6 | 14 |
| Phase 6 | 12 | 0 | 0 | 12 |
| Phase 7 | 16 | 12 | 0 | 28 |
| Phase 8 | 4 | 4 | 8 | 16 |
| Phase 9 | 0 | 4 | 0 | 4 + marketing |
| Phase 10 | 10 | 6 | 2 | 18 |
| **Total** | **82** | **52** | **26** | **160 hours** |

## Budget Summary

| Item | Monthly Cost | Notes |
|------|-------------|-------|
| Server (16 CPU / 32 GB) | $150-200 | Hetzner/OVH |
| Domain + DNS | $15 | Cloudflare |
| Email (Resend) | $0-20 | Free tier: 3k emails/month |
| Backup storage | $5 | Backblaze B2 |
| SSL certificates | $0 | Let's Encrypt |
| Analytics (PostHog) | $0 | Free tier: 1M events/month |
| Stripe | 2.9% + $0.30 | Only on Pro tier revenue |
| **Total (pre-revenue)** | **~$200/month** | |
| **Cost per user** | **$0.20/month** | At 1,000 users |

## Success Metrics

| Milestone | Target | Timeline |
|-----------|--------|----------|
| Platform live with HTTPS | ✓ | Week 1 |
| First 10 external agents connected | ✓ | Week 5 |
| 50 registered users | ✓ | Week 6 |
| First tournament completed | ✓ | Week 5 |
| 200 registered users | ✓ | Week 8 |
| SDK published to PyPI | ✓ | Week 3 |
| First paying Pro user | ✓ | Week 9 |
| 500 registered users | ✓ | Week 10 |
| 1,000 registered users | ✓ | Week 12 |
| $1,000 MRR | ✓ | Week 16 |
