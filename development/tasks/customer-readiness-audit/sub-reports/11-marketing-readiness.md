---
type: task
board: customer-readiness-audit
tags:
  - marketing
  - legal
  - onboarding
  - seo
  - documentation
  - sdk
  - support
---

# Sub-Report 11: Marketing & Non-Code Readiness Audit

**Date:** 2026-04-15
**Auditor:** Planner Agent
**Scope:** Legal pages, onboarding flow, documentation, SDK publishability, support infrastructure, SEO/marketing assets, waitlist functionality, feature flags/access control

---

## Executive Summary

The platform has **strong technical documentation** (54 MDX pages, 16 standalone docs, quickstart guide, 6 SDK examples) and a **functional waitlist system** backed by Neon Postgres. However, there are **critical gaps** in legal compliance (no Terms of Service, no Privacy Policy, no cookie consent), **no support infrastructure** (no contact email, no issue templates, no community channel), and **no OG images** for social sharing. The onboarding wizard exists but is incomplete in execution (wizard state not persisted, no email verification, no password reset). The SDK is well-structured for PyPI but has not been published yet.

**Verdict:** NOT ready for public customer launch. Ready for private beta with caveats.

---

## 1. Legal Pages

### Checklist

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1.1 | Terms of Service page | MISSING | No `/terms` route, no ToS content anywhere in frontend |
| 1.2 | Privacy Policy page | MISSING | No `/privacy` route, no privacy policy content |
| 1.3 | Cookie consent banner | MISSING | No cookie consent component; sidebar uses a cookie but no notice |
| 1.4 | GDPR compliance notice | MISSING | No GDPR-related content or consent mechanisms |
| 1.5 | Legal footer links | MISSING | Footer (`landing-footer.tsx`) has no legal links at all |
| 1.6 | Disclaimer (simulated trading, not financial advice) | MISSING | Coming Soon page says "zero risk" but no formal disclaimer |

### Evidence

- `Grep` for "terms", "privacy", "legal", "cookie" across `Frontend/src/` returned zero relevant matches (only sidebar cookie state and wallet privacy toggle)
- `Glob` for `Frontend/src/app/**/terms*/`, `Frontend/src/app/**/privacy*/`, `Frontend/src/app/**/legal*/` returned zero results
- No `(legal)` route group exists in the App Router
- `landing-footer.tsx` has 3 link columns (Platform, Get Started, Resources) but no Legal column
- `coming-soon.tsx` footer has only copyright text, no legal links

---

## 2. Onboarding Flow

### Checklist

| # | Item | Status | Notes |
|---|------|--------|-------|
| 2.1 | Registration form | PRESENT | `(auth)/register/page.tsx` — email, password, display name, Zod validation |
| 2.2 | Login form | PRESENT | `(auth)/login/page.tsx` — email/password, JWT auth, account info fetch |
| 2.3 | Onboarding wizard | PRESENT | `components/setup/` — 6 steps: register, create agent, API key, download skill, connect, verify |
| 2.4 | Post-registration redirect | PRESENT | Register -> shows credentials -> "Continue to Setup" button -> `/setup?from=register` |
| 2.5 | API key display (one-time) | PRESENT | Shown after registration with copy functionality |
| 2.6 | Email verification | MISSING | No email verification flow anywhere in backend or frontend |
| 2.7 | Password reset / forgot password | MISSING | No password reset endpoint or UI; grep across entire codebase returned zero matches |
| 2.8 | Welcome email | MISSING | No email sending infrastructure at all |
| 2.9 | Wizard state persistence | MISSING | Setup CLAUDE.md states: "Wizard state is local (not persisted) -- refreshing restarts the flow" |
| 2.10 | Account deletion / data export | MISSING | No self-service account deletion |

### Evidence

- `register/page.tsx` (lines 79-126): Full form with Zod validation, auto-login after registration, credentials shown once, then redirect to setup
- `setup/CLAUDE.md`: Documents 6 wizard steps (register, create agent, API key, download skill, connect agent, verify)
- Backend grep for `email_verif|verify_email|password_reset|forgot_password|reset_password` returned zero matches in `src/`
- The `plan-1000-users-a-to-z.md` explicitly lists "no email verification" as a blocker for public launch

---

## 3. Documentation

### Checklist

| # | Item | Status | Notes |
|---|------|--------|-------|
| 3.1 | Docs site infrastructure | PRESENT | Fumadocs-powered at `/docs`, standalone layout, Cmd+K search |
| 3.2 | Quickstart guide | PRESENT | `quickstart.mdx` — 5-minute guide: Docker, register, price, trade, portfolio |
| 3.3 | Getting Started series | PRESENT | 4 pages: index, first-agent, backtesting, rl-training |
| 3.4 | API reference (MDX) | PRESENT | 13 API pages: auth, market, trading, account, analytics, agents, strategies, testing, training, backtesting, battles, errors, rate-limits |
| 3.5 | SDK documentation | PRESENT | 5 pages: installation, sync-client, async-client, websocket-client, error-handling |
| 3.6 | Concepts documentation | PRESENT | 4 pages: how-it-works, agents, trading-rules, risk-management |
| 3.7 | Framework guides | PRESENT | 4 frameworks: LangChain, CrewAI, Agent Zero, OpenClaw |
| 3.8 | MCP documentation | PRESENT | 3 pages: overview, setup, tools |
| 3.9 | Gym documentation | PRESENT | 5 pages: overview, environments, rewards, training-tracking, examples |
| 3.10 | Strategy documentation | PRESENT | 4 pages: overview, indicators, testing, deployment |
| 3.11 | WebSocket documentation | PRESENT | 2 pages: connection, channels |
| 3.12 | Backtesting documentation | PRESENT | 3 pages: overview, guide, strategies |
| 3.13 | Battles documentation | PRESENT | 4 pages: overview, lifecycle, results-replay, live-monitoring |
| 3.14 | Code examples in docs | PRESENT | Quickstart has curl + Python SDK tabs for every step |
| 3.15 | Downloadable MD versions | PRESENT | `public/docs-md/` has 50+ static `.md` files for download |
| 3.16 | Docs REST API | PRESENT | 5 endpoints under `/api/v1/docs/` for programmatic access |
| 3.17 | Custom 404 for docs | PRESENT | `docs/[[...slug]]/not-found.tsx` with quick-links grid |
| 3.18 | Docs sitemap | PRESENT | `docs/sitemap.ts` generates per-page entries from Fumadocs source |
| 3.19 | Standalone docs (non-MDX) | PRESENT | 16 files in `docs/` including `skill.md`, `api_reference.md`, framework guides |

### Assessment

Documentation is **exceptionally complete** at 54 MDX pages across 12 sections, plus 16 standalone docs. This is one of the strongest areas of the platform.

**Minor gaps:**
- `quickstart.mdx` references `git clone https://github.com/your-org/agentexchange.git` — placeholder org name
- `getting-started/index.mdx` also has the same placeholder clone URL
- SDK install instructions reference `pip install agentexchange` but the package is not published to PyPI yet (only local `pip install -e sdk/` works)
- `gym_api_guide.md` references `pip install agentexchange-sdk` (wrong package name; should be `agentexchange`)

---

## 4. SDK Publishability

### Checklist

| # | Item | Status | Notes |
|---|------|--------|-------|
| 4.1 | `pyproject.toml` exists | PRESENT | Full metadata: name, version, description, license, classifiers, URLs |
| 4.2 | Package name defined | PRESENT | `agentexchange` (version 0.1.0) |
| 4.3 | License specified | PRESENT | MIT |
| 4.4 | Author/email | PRESENT | `AgentExchange` / `sdk@agentexchange.io` |
| 4.5 | Dependencies declared | PRESENT | `httpx>=0.28`, `websockets>=14.0` |
| 4.6 | README.md | PRESENT | Usage examples and installation instructions |
| 4.7 | py.typed marker | PRESENT | PEP 561 typed package |
| 4.8 | Classifiers | PRESENT | Alpha status, Python 3.12, Financial/Investment, AsyncIO, Typed |
| 4.9 | Project URLs | PRESENT | Homepage, Docs, Repository, Bug Tracker (all point to agentexchange.io/github) |
| 4.10 | PyPI name availability | UNKNOWN | `agentexchange` may or may not be taken on PyPI; needs manual check |
| 4.11 | Published to PyPI | NOT DONE | Package exists only locally; `pip install agentexchange` will fail for external users |
| 4.12 | SDK tests | MISSING | `sdk/CLAUDE.md` states: "No SDK tests exist in-tree yet" |
| 4.13 | Example scripts | PRESENT | 6 runnable examples in `sdk/examples/` |

### Assessment

The SDK is **structurally ready** for PyPI publication. The `pyproject.toml` is well-formed with proper classifiers, typed marker, and dependency declarations. The main gap is the absence of tests (no `sdk/tests/` files despite `pytest.ini_options` in config) and the fact that it has not actually been published.

---

## 5. Support Infrastructure

### Checklist

| # | Item | Status | Notes |
|---|------|--------|-------|
| 5.1 | Contact email in frontend | MISSING | No contact email anywhere in landing, footer, or coming-soon pages |
| 5.2 | Support/feedback form | MISSING | No form component for user feedback or support requests |
| 5.3 | GitHub issue templates | MISSING | `.github/` contains only `workflows/deploy.yml` and `workflows/test.yml`; no `ISSUE_TEMPLATE/` |
| 5.4 | Discord/Slack community link | MISSING | No community links anywhere in frontend |
| 5.5 | Status page (e.g., Instatus, Betteruptime) | MISSING | No status page configuration found |
| 5.6 | Social media links | MISSING | No Twitter/X, GitHub, or social links in header, footer, or coming-soon page |
| 5.7 | FAQ page | MISSING | No FAQ content anywhere |

### Assessment

Support infrastructure is **entirely absent**. There is no way for a user to contact the team, report bugs, join a community, or check service status. This is a significant gap for any public-facing product.

---

## 6. SEO & Marketing Assets

### Checklist

| # | Item | Status | Notes |
|---|------|--------|-------|
| 6.1 | Root layout meta tags | PARTIAL | Title template present (`%s | AI Trading Agent`), description present, but generic |
| 6.2 | Coming Soon page OG tags | PRESENT | `openGraph` and `twitter` card metadata in `page.tsx` |
| 6.3 | Landing page OG tags | PRESENT | `openGraph` and `twitter` card metadata in `landing/page.tsx` |
| 6.4 | OG image | MISSING | No `opengraph-image.png` in `public/` or any app directory; OG tags reference no image URL |
| 6.5 | Twitter card image | MISSING | `twitter.card: "summary_large_image"` set but no image provided |
| 6.6 | Favicon | PRESENT | `favicon.ico` exists |
| 6.7 | `sitemap.ts` | PRESENT | 5 URLs: `/`, `/login`, `/register`, `/market`, `/leaderboard` |
| 6.8 | Docs sitemap | PRESENT | Separate `docs/sitemap.ts` generates entries for all doc pages |
| 6.9 | `robots.ts` | PRESENT | Allows `/`, disallows `/api/`, `/dashboard/`, `/wallet/`, `/settings/` |
| 6.10 | Blog / changelog page | MISSING | No blog or changelog route |
| 6.11 | Product screenshots for sharing | PRESENT | 9 screenshots in `public/screenshots/` (dashboard, markets, wallet, etc.) |
| 6.12 | Logo assets | PRESENT | Multiple logo concepts in `public/logos/` (12 SVGs across 4 concepts) |
| 6.13 | Landing page | PRESENT | Full marketing page at `/landing` with hero, features, how-it-works, frameworks, CTA |
| 6.14 | Sitemap includes `/landing` | MISSING | `sitemap.ts` lists `/` but not `/landing`; docs pages also not in main sitemap |

### Evidence

- `layout.tsx` (line 24-30): Only title template and basic description; no `openGraph.images` property
- `page.tsx` (line 8-19): Has `openGraph` and `twitter` metadata but no `images` array
- `Glob` for `Frontend/public/og*` returned zero results
- `sitemap.ts`: Only 5 URLs listed — missing `/landing`, `/docs`, individual doc pages (docs sitemap is separate)
- `robots.ts`: Correctly blocks private routes

---

## 7. Waitlist System

### Checklist

| # | Item | Status | Notes |
|---|------|--------|-------|
| 7.1 | Waitlist form on Coming Soon page | PRESENT | Email input + submit button with loading/success/error states |
| 7.2 | Waitlist API endpoint | PRESENT | `Frontend/src/app/api/waitlist/route.ts` — POST handler |
| 7.3 | Database storage | PRESENT | Auto-creates `waitlist` table in Neon Postgres; handles duplicate emails |
| 7.4 | Backend model | PRESENT | `WaitlistEntry` model in `src/database/models.py` with UUID PK, email, source, created_at |
| 7.5 | Success/error feedback | PRESENT | Shows "You're in!" on success, "Already on the list" on duplicate, error messages on failure |
| 7.6 | Confirmation email | MISSING | No email sent after waitlist signup |
| 7.7 | Admin view of waitlist | MISSING | No way to view/export waitlist entries from the frontend |
| 7.8 | Waitlist export mechanism | MISSING | No script or endpoint to export waitlist data |

### Assessment

The waitlist system **works end-to-end** for collecting emails. The Coming Soon page at `/` has a professional waitlist form with proper error handling, duplicate detection, and a smooth UX. However, there is no confirmation email (users cannot verify their signup), no admin view to manage the list, and no export mechanism. 

**Note:** The waitlist API uses a separate Neon Postgres database (via `DATABASE_URL` env var in the Next.js server) that is independent from the main platform database. The `WaitlistEntry` model in the backend's `models.py` appears to be a separate, unused model.

---

## 8. Feature Flags & Access Control

### Checklist

| # | Item | Status | Notes |
|---|------|--------|-------|
| 8.1 | Free vs paid tier system | MISSING | No subscription, billing, or tier system |
| 8.2 | Feature flags | PARTIAL | Agent permissions system has `capabilities` JSONB (feature flag map) and roles (`viewer`, `paper_trader`, `live_trader`, `admin`) but this is agent-scoped, not user-scoped |
| 8.3 | Admin panel | MISSING | No admin UI; `grafana_admin_password` exists in config but only for Grafana |
| 8.4 | Usage quotas per user | MISSING | Rate limiting exists (per API key, sliding window via Redis) but no per-account usage caps |
| 8.5 | Starting balance caps | MISSING | `plan-1000-users-a-to-z.md` lists "no starting_balance cap" as a blocker |

### Assessment

The platform has **sophisticated agent-level permissions** (roles, capabilities, budget limits, enforcement) but **no user-facing tier system**. All users get the same features. There is no admin panel to manage users, view signups, or moderate activity. Rate limiting exists at the API level but there are no usage quotas (e.g., max agents per account, max backtests per day).

---

## Summary: Readiness Matrix

### Category Scores

| Category | Score | Grade |
|----------|-------|-------|
| Legal Pages | 0/6 | F |
| Onboarding Flow | 5/10 | D |
| Documentation | 19/19 | A+ |
| SDK Publishability | 10/13 | B+ |
| Support Infrastructure | 0/7 | F |
| SEO & Marketing Assets | 8/14 | C |
| Waitlist System | 5/8 | C+ |
| Feature Flags / Access Control | 1/5 | F |
| **Overall** | **48/82 (59%)** | **D+** |

---

## Launch Blockers (MUST exist before ANY customer)

These items are non-negotiable for any public-facing product, even a beta:

| # | Blocker | Risk if Missing | Effort |
|---|---------|-----------------|--------|
| B1 | **Terms of Service page** | Legal exposure; no user agreement on acceptable use | 1 day (content + route) |
| B2 | **Privacy Policy page** | GDPR/CCPA violation; cannot legally collect emails or user data | 1 day (content + route) |
| B3 | **Trading disclaimer** | Liability risk; users must acknowledge simulated trading, not financial advice | 0.5 day |
| B4 | **Contact email or support channel** | Users have no way to report issues or get help | 0.5 day |
| B5 | **OG image for social sharing** | Every share on Twitter/LinkedIn shows a blank preview; kills organic growth | 0.5 day |
| B6 | **Cookie consent (if targeting EU)** | GDPR fine risk for the sidebar state cookie | 0.5 day (if EU users expected) |
| B7 | **Fix placeholder git clone URLs in docs** | Users cannot follow quickstart; `your-org` placeholder breaks first impression | 0.5 hour |

**Total blocker effort: ~4 days**

---

## High Priority (should exist before marketing push)

| # | Item | Impact | Effort |
|---|------|--------|--------|
| H1 | **Password reset flow** | Users locked out permanently if they forget password | 2-3 days (backend + email + UI) |
| H2 | **Email verification** | Fake/spam accounts; waitlist reliability | 2 days (backend + email service) |
| H3 | **Publish SDK to PyPI** | Docs say `pip install agentexchange` which fails; breaks trust | 0.5 day |
| H4 | **GitHub issue templates** | No structured way for developers to report bugs | 0.5 day |
| H5 | **Social media links in footer/header** | No way for users to follow or engage | 0.5 day (need Twitter/X account first) |
| H6 | **Blog or changelog page** | No mechanism to communicate updates to users | 2 days |
| H7 | **Waitlist confirmation email** | Users don't know if signup worked; no engagement hook | 1 day (need email provider) |
| H8 | **Status page** | Users can't tell if outages are them or the platform | 0.5 day (Betteruptime free tier) |
| H9 | **Legal footer links on all pages** | Footer lacks Terms/Privacy links even after they exist | 0.5 day |
| H10 | **Add /landing and /docs to sitemap** | Search engines miss 50+ pages of content | 0.5 hour |

**Total high-priority effort: ~10-12 days**

---

## Nice-to-Have (can add iteratively post-launch)

| # | Item | Impact | Effort |
|---|------|--------|--------|
| N1 | FAQ page | Reduces support volume | 1 day |
| N2 | Waitlist admin view / export | Team can manage and communicate with signups | 1 day |
| N3 | Welcome email after registration | Better first impression, engagement | 1 day |
| N4 | Discord/Slack community | Community building, support deflection | 0.5 day (setup) |
| N5 | Account deletion / data export | GDPR right-to-erasure compliance | 2 days |
| N6 | Onboarding wizard persistence | Users don't lose progress on refresh | 1 day |
| N7 | Free/paid tier system | Monetization; limit abuse | 5+ days |
| N8 | Admin panel | User management, moderation | 5+ days |
| N9 | Cookie policy page | Full GDPR compliance | 0.5 day |
| N10 | Usage quotas per account | Prevent resource abuse at scale | 2 days |

---

## Recommended Launch Sequence

### Pre-Launch (Week 1): Legal & Blockers
**Goal:** Eliminate all legal exposure and critical first-impression gaps.

| Day | Tasks | Owner |
|-----|-------|-------|
| Mon | B1: Write Terms of Service, create `/terms` route | Legal + Frontend |
| Mon | B2: Write Privacy Policy, create `/privacy` route | Legal + Frontend |
| Tue | B3: Add trading disclaimer to registration flow and footer | Frontend |
| Tue | B5: Design and add OG image (`opengraph-image.png`) | Design + Frontend |
| Tue | B7: Fix placeholder URLs in quickstart docs | Frontend |
| Wed | B4: Set up support email (support@tradeready.io), add to footer and coming-soon page | Infra |
| Wed | H9: Add legal footer links to `landing-footer.tsx` and `coming-soon.tsx` | Frontend |
| Wed | H10: Add `/landing` and `/docs` to `sitemap.ts` | Frontend |
| Thu | B6: Add cookie consent banner (if targeting EU) | Frontend |
| Thu | H8: Set up Betteruptime/Instatus status page | Infra |
| Fri | H5: Create Twitter/X account, add social links to footer | Marketing |

### Soft Launch (Week 2): Developer Experience
**Goal:** Make the SDK installable and create basic feedback channels.

| Day | Tasks | Owner |
|-----|-------|-------|
| Mon | H3: Publish `agentexchange` to PyPI (test with TestPyPI first) | Backend |
| Mon | H4: Create GitHub issue templates (bug report, feature request, question) | Backend |
| Tue | H7: Set up email provider (e.g., Resend, Postmark), send waitlist confirmation | Backend |
| Wed-Thu | H1: Implement password reset flow (backend endpoint + email + frontend form) | Full stack |
| Fri | H2: Email verification on registration | Full stack |

### Public Announce (Week 3): Content & Community
**Goal:** Have a marketing-ready presence for announcement posts.

| Day | Tasks | Owner |
|-----|-------|-------|
| Mon | H6: Create `/blog` or `/changelog` route, write first post (launch announcement) | Frontend + Content |
| Tue | N1: Create FAQ page from anticipated questions | Content |
| Tue | N4: Set up Discord server, add invite link to footer | Community |
| Wed | N2: Build waitlist admin view or export script | Backend |
| Thu | N3: Welcome email after registration | Backend |
| Fri | Announcement post on Twitter/X, Hacker News, Reddit r/algotrading, r/LocalLLaMA | Marketing |

### Post-Launch (Week 4+): Iterate
- N5: Account deletion for GDPR compliance
- N6: Persist onboarding wizard state
- N7-N8: Tier system and admin panel (when monetization timeline is defined)
- N10: Usage quotas based on real usage patterns observed in week 1-2

---

## Marketing Channel Recommendations

### Primary Channels (Developer Audience)

| Channel | Why | Timing |
|---------|-----|--------|
| **Twitter/X** | AI/crypto developer community is extremely active; Claude/GPT integration angle is viral | Day 1 of public announce |
| **Hacker News** (Show HN) | Developer-first product; "simulated exchange for AI agents" is a novel Show HN | Day 1 of public announce |
| **Reddit r/algotrading** | Direct target audience; backtesting + strategy features resonate | Day 1-2 |
| **Reddit r/LocalLLaMA** | MCP server + skill.md integration angle; local AI agent developers | Day 1-2 |
| **Reddit r/langchain, r/ChatGPT** | Framework integration guides provide natural content | Week 1 |

### Secondary Channels

| Channel | Why | Timing |
|---------|-----|--------|
| **Dev.to / Hashnode** | Tutorial-style posts ("Build a Trading Agent in 5 Minutes") | Week 2 |
| **Discord communities** | AI agent framework Discords (LangChain, CrewAI, Anthropic) | Week 2 |
| **Product Hunt** | Good for initial visibility spike | Week 3 (after bugs from Week 1-2 are fixed) |
| **YouTube** | Screen recording: "Watch an AI Agent Trade Crypto in Real-Time" | Week 3-4 |

### Content Angles That Will Resonate

1. **"5 lines of Python to give your AI agent a trading API"** — the simplicity angle
2. **"AI Agent Battle Royale"** — the competitive/gamification angle  
3. **"Backtest before you bet"** — the risk-management angle
4. **"Works with Claude, GPT-4o, LLaMA, and any MCP client"** — the universal compatibility angle
5. **"600+ crypto pairs, zero dollars at risk"** — the safety angle

---

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Legal action from users due to missing ToS/Privacy | Medium | HIGH | Blockers B1, B2 — must ship before any public traffic |
| User abandonment at registration (no password reset) | High | MEDIUM | H1 — password reset flow |
| SDK install failure kills first impression | High | HIGH | H3 — publish to PyPI before any announcement |
| Spam/abuse accounts with no email verification | High | MEDIUM | H2 — email verification |
| Support requests with no channel | Certain | MEDIUM | B4 — at minimum a support email |
| Social shares look unprofessional (no OG image) | High | MEDIUM | B5 — single image asset needed |
| Users cannot find platform during outage | Medium | MEDIUM | H8 — status page |

---

## Final Verdict

**The platform's code, features, and documentation are genuinely impressive for a pre-launch product.** The 54-page docs site, 6 SDK examples, 4 framework guides, and comprehensive API coverage put it well ahead of most early-stage developer tools.

**The gaps are entirely in non-code prerequisites:** legal pages, support channels, email infrastructure, social presence, and PyPI publication. These are all solvable in approximately 3 weeks of focused work.

**Recommended launch posture:**
- **Week 1:** Fix blockers (legal, OG, support email) and soft-launch to waitlist as private beta
- **Week 2:** SDK on PyPI, password reset, email verification  
- **Week 3:** Public announcement with blog post, social presence, and community
