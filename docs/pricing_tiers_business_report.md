# Pricing Tiers & Monetization Strategy — Business Report

> **Date:** 2026-03-17
> **Status:** Proposal — pending business review
> **Audience:** Founders, product, engineering

---

## 1. Executive Summary

We're monetizing the platform through API access tiers. The core challenge: **free must be generous enough that users build real workflows and get hooked, but limited enough that serious users convert to Pro.** This report maps every platform feature to a tier, defines the limits, and outlines implementation priority.

**Current state:** Zero tier logic exists in the codebase. All accounts get identical access — same rate limits, unlimited backtests, unlimited agents. The Account model has no `plan` field. Everything below is greenfield.

---

## 2. Pricing Philosophy

### The Free Tier Trap to Avoid

Too restrictive = users bounce before experiencing value. If a trader can't run enough backtests to validate one strategy, they'll leave before they ever need Pro.

### The Conversion Trigger

Users convert when they hit a limit **while actively succeeding**. The best limits are the ones that kick in right when the user thinks "this is working, I need more." That means:

- **Backtests:** 10/month is the sweet spot. A serious user testing a strategy needs 3-5 runs to iterate (different params, different pairs, different timeframes). 10 lets them validate one strategy well but not iterate on multiple strategies simultaneously.
- **Agents:** 2 free agents lets users experience multi-agent trading (the core differentiator) but not build a full portfolio of specialized agents.
- **Battles:** 3/month gives users a taste of the competitive feature without letting them run tournaments.
- **API rate limits:** Reduced but not crippled — enough for a single bot, not enough for a fleet.

---

## 3. Tier Definitions

### 3.1 Free Tier

**Target user:** Individual trader exploring the platform, testing their first strategy, deciding if it's worth paying for.

| Feature | Free Limit | Rationale |
|---------|-----------|-----------|
| **Agents** | 2 active | Experience multi-agent, but can't build a fleet |
| **Backtests/month** | 10 | Enough to validate 1-2 strategies with iteration |
| **Battles/month** | 3 | Taste the feature, can't grind the leaderboard |
| **Concurrent battles** | 1 | No parallel tournaments |
| **Starting balance** | 10,000 USDT | Same as Pro — don't handicap the trading experience |
| **Trading pairs** | All 600+ | Don't restrict market access — that feels punishing |
| **Order types** | All (market, limit, stop-loss, TP) | Don't cripple trading — that kills retention |
| **API rate: Orders** | 30 req/min | Enough for 1 bot, not 5 |
| **API rate: Market data** | 300 req/min | Enough for basic polling, not HFT-style |
| **API rate: General** | 120 req/min | Proportional reduction |
| **WebSocket subscriptions** | 5 per connection | Half of current cap |
| **WebSocket connections** | 1 per account | Single stream |
| **Portfolio analytics** | Daily snapshots only | No minute/hourly granularity |
| **Candle history depth** | 30 days | Enough for short-term backtests |
| **Leaderboard** | View only (own rank hidden) | Teaser — see top traders but can't see where you stand |
| **Risk profile customization** | No | Locked to defaults |
| **Account resets** | 3/month | Prevents infinite retry gaming |
| **Monthly API calls (total)** | 50,000 | Hard ceiling across all endpoints |

### 3.2 Pro Tier

**Target user:** Active algo trader running multiple strategies, needs reliable throughput and full analytics.

**Price suggestion:** $29-49/month (competitive with TradingView Pro at $14.95, QuantConnect at $8-24, but we offer real-time data + agent battles which is unique).

| Feature | Pro Limit | Rationale |
|---------|----------|-----------|
| **Agents** | 25 active | Full portfolio of specialized agents |
| **Backtests/month** | Unlimited | Core workflow, no friction |
| **Battles/month** | Unlimited | Full tournament access |
| **Concurrent battles** | 5 | Run multiple experiments in parallel |
| **Starting balance** | 10,000 - 100,000 USDT (configurable) | Higher balance for realistic large-cap simulation |
| **Trading pairs** | All 600+ | Same |
| **Order types** | All | Same |
| **API rate: Orders** | 100 req/min | Current default (unchanged) |
| **API rate: Market data** | 1,200 req/min | Current default (unchanged) |
| **API rate: General** | 600 req/min | Current default (unchanged) |
| **WebSocket subscriptions** | 10 per connection | Current cap |
| **WebSocket connections** | 5 per account | Multi-stream monitoring |
| **Portfolio analytics** | Minute + Hourly + Daily | Full granularity |
| **Candle history depth** | Full history | All backfilled data |
| **Leaderboard** | Full access + own ranking | See where you stand |
| **Risk profile customization** | Full | Tune all 6 risk parameters per agent |
| **Account resets** | Unlimited | |
| **Monthly API calls (total)** | Unlimited | No hard ceiling |
| **Priority support** | Email | |
| **SDK access** | Full | Python SDK unrestricted |

### 3.3 Enterprise Tier

**Target user:** Teams, hedge fund interns, education institutions, API resellers.

**Price:** Custom ($199+/month or annual contract)

| Feature | Enterprise Limit |
|---------|-----------------|
| **Agents** | Unlimited |
| **Everything Pro has** | Unlimited |
| **Team accounts** | Multiple users under one org |
| **Custom starting balance** | Any amount |
| **Dedicated support** | Slack/Discord channel |
| **Custom data feeds** | On request |
| **White-label API** | On request |
| **SLA** | 99.9% uptime guarantee |

---

## 4. What We DON'T Restrict on Free (and Why)

| Feature | Why it stays free |
|---------|------------------|
| **All 600+ trading pairs** | Restricting pairs feels arbitrary and punishing. A user with 10 pairs can't properly test a diversified strategy. |
| **All order types** | If free users can only do market orders, they can't test real strategies. Stop-loss/TP are essential risk management — removing them makes the platform feel broken. |
| **Starting balance (10K USDT)** | A smaller balance doesn't save us resources — it just makes the experience worse. The simulation costs the same whether it's 1K or 100K. |
| **Real-time prices** | Price data comes from Binance WS regardless. Gating it adds complexity for zero cost savings. |
| **Trading fees (0.1%)** | Same fee for everyone — this is a simulation parameter, not a monetization lever. |

---

## 5. Monthly Usage Tracking — What We Need to Meter

### 5.1 Counters to Track

| Meter | How to Count | Storage |
|-------|-------------|---------|
| Backtests created this month | `COUNT(*) FROM backtest_sessions WHERE account_id = ? AND created_at >= month_start` | DB query (or Redis counter) |
| Battles created this month | `COUNT(*) FROM battles WHERE account_id = ? AND created_at >= month_start` | DB query (or Redis counter) |
| Active agents | `COUNT(*) FROM agents WHERE account_id = ? AND status = 'active'` | DB query |
| Active battles | `COUNT(*) FROM battles WHERE account_id = ? AND status IN ('active', 'paused')` | DB query |
| Monthly API calls | Redis counter: `usage:{account_id}:api_calls:{YYYY-MM}` | Redis with TTL |
| Account resets this month | Redis counter or DB column | Redis or DB |
| WebSocket connections | In-memory count in `ConnectionManager` | Memory |

### 5.2 Recommended Implementation: Usage Tracking Table

```sql
CREATE TABLE account_usage (
    id          BIGSERIAL PRIMARY KEY,
    account_id  UUID NOT NULL REFERENCES accounts(id),
    month       DATE NOT NULL,  -- first day of month, e.g. '2026-03-01'

    backtests_created   INT NOT NULL DEFAULT 0,
    battles_created     INT NOT NULL DEFAULT 0,
    api_calls_total     BIGINT NOT NULL DEFAULT 0,
    account_resets      INT NOT NULL DEFAULT 0,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(account_id, month)
);
```

Why a dedicated table instead of just counting from existing tables:
- **Performance:** `COUNT(*)` on large tables is slow. Increment a counter instead.
- **Simplicity:** One place to check all usage.
- **History:** Can show users their usage trends over time.
- **Billing:** If we add payments later, usage records are the billing source.

---

## 6. Competitive Analysis

| Platform | Free Tier | Pro Price | Key Limits on Free |
|----------|-----------|-----------|-------------------|
| **TradingView** | 1 chart, 3 indicators, delayed data | $14.95/mo | No real-time, limited indicators |
| **QuantConnect** | 1 backtest at a time, 10hr compute/month | $8-24/mo | Compute time, concurrent limits |
| **Alpaca** | Unlimited paper trading, 200 req/min | $0 (commission-based) | No backtesting, real money only |
| **3Commas** | 1 bot, limited pairs | $29/mo | Bot count, pair restrictions |
| **Pionex** | 12 free bots, all pairs | $0 (spread-based) | No backtesting, limited analytics |
| **Us (proposed)** | 2 agents, 10 backtests, 3 battles | $29-49/mo | Agent count, backtest/battle count, rate limits |

### Our Differentiators (what justifies the price)

1. **Multi-agent architecture** — No competitor lets you run named AI agents with individual wallets, risk profiles, and trading histories
2. **Agent battles** — Unique competitive feature, no equivalent anywhere
3. **Real Binance data** — Live prices, not delayed or synthetic
4. **Full backtesting** — Historical replay with the same engine used for live trading
5. **SDK + MCP** — Programmatic access for AI-native workflows (Claude Desktop integration)

---

## 7. Conversion Funnel — How Free Users Hit the Wall

### Scenario 1: The Strategy Tester
```
Week 1: Creates account, runs 3 backtests exploring the platform     → 7 remaining
Week 2: Builds first strategy, runs 4 backtests iterating params      → 3 remaining
Week 3: Wants to test on different pairs and timeframes               → Hits limit
         ↓
         "I need more backtests" → Upgrade prompt
```

### Scenario 2: The Bot Builder
```
Week 1: Creates 1 agent, starts trading via API                      → 1 agent remaining
Week 2: Strategy works, wants to diversify across strategies          → Creates 2nd agent
Week 3: Wants a conservative agent + aggressive agent + scalper       → Hits limit
         ↓
         "I need more agents" → Upgrade prompt
```

### Scenario 3: The Competitor
```
Month 1: Runs 2 battles, loves seeing agents compete                  → 1 remaining
         Wants to run a tournament bracket with friends                → Hits limit
         ↓
         "I need more battles" → Upgrade prompt
```

### Scenario 4: The Data Analyst
```
Week 1: Polls market data at 300/min, works fine for 1 pair
Week 2: Wants to monitor 20 pairs simultaneously                     → Rate limit
         ↓
         "I need higher rate limits" → Upgrade prompt
```

---

## 8. What Users See When They Hit a Limit

### API Response (new error code)

```json
{
  "error": {
    "code": "QUOTA_EXCEEDED",
    "message": "Free plan limit reached: 10 backtests per month. Upgrade to Pro for unlimited backtests.",
    "details": {
      "resource": "backtests",
      "limit": 10,
      "used": 10,
      "plan": "free",
      "resets_at": "2026-04-01T00:00:00Z",
      "upgrade_url": "/pricing"
    }
  }
}
```

HTTP Status: **403 Forbidden** (not 429 — this is a plan limit, not a rate limit)

### Frontend Upgrade Prompt

When a user hits any plan limit, show a modal:
- Current usage vs limit (progress bar)
- What Pro unlocks
- One-click upgrade button
- "Resets in X days" for monthly limits

---

## 9. Revenue Projections (Conservative)

| Metric | Month 1 | Month 3 | Month 6 | Month 12 |
|--------|---------|---------|---------|----------|
| Free signups | 500 | 2,000 | 5,000 | 15,000 |
| Free → Pro conversion | 2% | 3% | 4% | 5% |
| Pro subscribers | 10 | 60 | 200 | 750 |
| Pro price (avg) | $39 | $39 | $39 | $39 |
| MRR | $390 | $2,340 | $7,800 | $29,250 |
| Enterprise (est.) | $0 | $0 | $400 | $2,000 |
| **Total MRR** | **$390** | **$2,340** | **$8,200** | **$31,250** |

Assumptions:
- 2-5% conversion is standard for developer tools (Stripe reports 3-5% for dev platforms)
- Enterprise comes later once platform proves value
- Churn not modeled (assume 5-8% monthly for SaaS)

---

## 10. Implementation Priority

### Phase 1: Foundation (Week 1-2)
1. Add `plan` field to Account model (`free`, `pro`, `enterprise`) with default `free`
2. Create `account_usage` table and Alembic migration
3. Create `QuotaService` that checks plan limits before resource creation
4. Add `QUOTA_EXCEEDED` error to exception hierarchy

### Phase 2: Enforce Limits (Week 2-3)
5. Gate backtest creation: check monthly count before `create_session()`
6. Gate agent creation: check active count before `create_agent()`
7. Gate battle creation: check monthly + concurrent count before `create_battle()`
8. Adjust rate limits per plan in `RateLimitMiddleware`
9. Gate WebSocket subscription count per plan
10. Add `GET /account/usage` endpoint returning current usage vs limits

### Phase 3: Billing Integration (Week 3-4)
11. Integrate Stripe (or LemonSqueezy for simplicity)
12. Webhook handler for subscription events (created, updated, cancelled)
13. Auto-upgrade `plan` field on payment success
14. Auto-downgrade on payment failure (grace period: 7 days)

### Phase 4: Frontend (Week 4-5)
15. Pricing page
16. Usage dashboard (progress bars per limit)
17. Upgrade modals when limits are hit
18. Plan badge in header/sidebar

### Phase 5: Polish (Week 5-6)
19. Upgrade prompt emails (triggered by hitting 80% of a limit)
20. Monthly usage reset Celery task (1st of each month, 00:00 UTC)
21. Admin dashboard for usage analytics
22. Promo codes / trial periods for Pro

---

## 11. Account Model Change

```python
# Addition to Account model (src/database/models.py)
plan: Mapped[str] = mapped_column(
    VARCHAR(20),
    nullable=False,
    server_default=text("'free'"),
    index=True,
)
# Valid values: 'free', 'pro', 'enterprise'
```

### Plan Limits Config (new file: `src/config.py` or `src/accounts/plans.py`)

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class PlanLimits:
    max_agents: int
    max_backtests_per_month: int
    max_battles_per_month: int
    max_concurrent_battles: int
    max_api_calls_per_month: int | None  # None = unlimited
    rate_limit_orders: int       # req/min
    rate_limit_market: int       # req/min
    rate_limit_general: int      # req/min
    max_ws_subscriptions: int
    max_ws_connections: int
    max_account_resets_per_month: int | None
    analytics_snapshot_types: tuple[str, ...]
    candle_history_days: int | None  # None = unlimited
    risk_profile_customizable: bool
    leaderboard_full_access: bool

PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(
        max_agents=2,
        max_backtests_per_month=10,
        max_battles_per_month=3,
        max_concurrent_battles=1,
        max_api_calls_per_month=50_000,
        rate_limit_orders=30,
        rate_limit_market=300,
        rate_limit_general=120,
        max_ws_subscriptions=5,
        max_ws_connections=1,
        max_account_resets_per_month=3,
        analytics_snapshot_types=("daily",),
        candle_history_days=30,
        risk_profile_customizable=False,
        leaderboard_full_access=False,
    ),
    "pro": PlanLimits(
        max_agents=25,
        max_backtests_per_month=None,  # unlimited
        max_battles_per_month=None,
        max_concurrent_battles=5,
        max_api_calls_per_month=None,
        rate_limit_orders=100,
        rate_limit_market=1_200,
        rate_limit_general=600,
        max_ws_subscriptions=10,
        max_ws_connections=5,
        max_account_resets_per_month=None,
        analytics_snapshot_types=("minute", "hourly", "daily"),
        candle_history_days=None,
        risk_profile_customizable=True,
        leaderboard_full_access=True,
    ),
    "enterprise": PlanLimits(
        max_agents=None,  # unlimited
        max_backtests_per_month=None,
        max_battles_per_month=None,
        max_concurrent_battles=None,
        max_api_calls_per_month=None,
        rate_limit_orders=500,
        rate_limit_market=5_000,
        rate_limit_general=3_000,
        max_ws_subscriptions=50,
        max_ws_connections=20,
        max_account_resets_per_month=None,
        analytics_snapshot_types=("minute", "hourly", "daily"),
        candle_history_days=None,
        risk_profile_customizable=True,
        leaderboard_full_access=True,
    ),
}
```

---

## 12. Key Decisions Still Needed

| Decision | Options | Recommendation |
|----------|---------|----------------|
| **Price point** | $19, $29, $39, $49/mo | $39/mo — premium enough to signal value, low enough for individual traders |
| **Annual discount** | 0%, 15%, 20%, 25% | 20% off annual ($374/yr vs $468) — standard SaaS |
| **Payment processor** | Stripe, LemonSqueezy, Paddle | LemonSqueezy for MVP (handles tax globally, simpler API), migrate to Stripe at scale |
| **Downgrade grace period** | Immediate, 3 days, 7 days, 30 days | 7 days — enough time to fix payment issues without losing data |
| **Over-limit behavior** | Hard block vs soft warning | Hard block with clear upgrade path — soft warnings train users to ignore limits |
| **Existing user migration** | Free, grandfathered Pro, limited promo | 30-day Pro trial for all existing users — reward early adopters, drive conversion |
| **Backtest history on downgrade** | Keep data, delete data | Keep all data read-only — deletion feels punishing and destroys trust |
| **Trial period for new signups** | None, 7-day Pro, 14-day Pro | 14-day Pro trial — lets users experience full platform before deciding |

---

## 13. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Free limits too tight → users bounce | Lost growth, negative reviews | Monitor signup→first-backtest→churn funnel. If >60% leave before running 3 backtests, raise limits |
| Free limits too generous → no conversion | Revenue stays at zero | Track how many free users hit limits. If <10% ever hit a limit, tighten |
| Rate limit changes break existing bots | User frustration, support load | Announce 30 days before enforcement. Version the rate limits. |
| Enterprise demand before we're ready | Lost deals | Put "Contact us" and collect emails. Don't build until we have 3+ serious inquiries |
| Competitors copy our agent/battle features | Commoditization | Move fast. Our advantage is being first — network effects from battles and leaderboards compound |

---

## 14. Success Metrics to Track

| Metric | Target (Month 3) | Target (Month 12) |
|--------|------------------|-------------------|
| Free → Pro conversion rate | 3% | 5% |
| % of free users hitting at least 1 limit | 25% | 35% |
| Pro monthly churn | <8% | <5% |
| Time from signup to first backtest | <24 hours | <12 hours |
| Time from signup to hitting first limit | 7-14 days | 7-14 days |
| NPS score | >30 | >50 |
| Monthly active users (MAU) | 600 | 5,000 |

---

<!-- last-updated: 2026-03-17 -->
