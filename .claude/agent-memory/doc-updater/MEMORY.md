# doc-updater — Persistent Memory

<!-- last-updated: 2026-04-07 (Task 15) -->

## Documentation Inventory

### docs/ (public-facing, 14 files)

| File | Audience | Update trigger |
|------|----------|----------------|
| `docs/api_reference.md` | Backend devs, agent builders | Any REST endpoint change |
| `docs/skill.md` | LLM agents (system prompt injection) | Any API or workflow change |
| `docs/mcp_server.md` | MCP client users | MCP tool additions/removals (current: 58 tools, 10 categories) |
| `docs/quickstart.md` | New users | Auth flow or SDK changes |
| `docs/backtesting-guide.md` | Agent devs | Backtest endpoint changes |
| `docs/backtesting-explained.md` | Non-technical users | Keep in sync with guide |
| `docs/rate_limits.md` | Developers | Rate limit tier changes |
| `docs/gym_api_guide.md` | Agent devs, RL researchers | Gym env or Strategy API changes |
| `docs/framework_guides/langchain.md` | LangChain devs | SDK or API changes |
| `docs/framework_guides/crewai.md` | CrewAI devs | SDK or API changes |
| `docs/framework_guides/agent_zero.md` | Agent Zero devs | skill.md or SDK changes |
| `docs/framework_guides/openclaw.md` | OpenClaw devs | skill.md or SDK changes |
| `docs/getting-started-agents.md` | External agent devs | 9-step guide changes; new platform features |
| `docs/architecture-overview.md` | External agent devs | Connection method or isolation model changes |
| `docs/tradeready_research.md` | Internal | Competitive analysis (frozen) |
| `docs/pricing_tiers_business_report.md` | Internal | Business model (frozen) |

### SDK docs (sdk/)

- `sdk/CLAUDE.md` — sync client patterns, async client, WebSocket client (48 methods across 10 groups as of 2026-04-07)
- SDK install: `pip install -e sdk/`; package: `AgentExchangeClient`, `AsyncAgentExchangeClient`, `AgentExchangeWS`
- `sdk/examples/` — 6 runnable scripts (basic_backtest, rl_training, genetic_optimization, strategy_tester, webhook_integration, getting_started)

### Fumadocs site (Frontend/content/docs/)

- 50 MDX files across 12 sections: `api`, `backtesting`, `battles`, `concepts`, `frameworks`, `gym`, `mcp`, `sdk`, `strategies`, `websocket`, plus root index/quickstart/skill-reference
- 11 `meta.json` sidebar config files
- Rendered at `/docs` route via Fumadocs (separate from dashboard `/docs-hub`)
- `scripts/generate-docs-md.ts` regenerates static `.md` files from MDX content

## CLAUDE.md Index (70 files total)

**Update pattern — always add to "Recent Changes" section:**
```markdown
## Recent Changes
- `YYYY-MM-DD` — Brief description of what changed
```

**Timestamp format:** `<!-- last-updated: YYYY-MM-DD -->` in header

**File inventory tables** — glob the directory and add/remove rows for new/deleted files.

**Test counts** — when test counts change, update `tests/unit/CLAUDE.md` ("72 files, 1203 tests") and `tests/integration/CLAUDE.md` ("24 files, 504 tests").

## Priority Update Rules

1. `skill.md` is consumed by LLM agents at runtime — changes affect agent behavior directly. Keep self-contained, no external links.
2. `api_reference.md` is the source of truth for API shapes; update `backtesting-explained.md` in sync for plain-English descriptions.
3. When MCP tools change, update both `mcp_server.md` and `skill.md` (agents use both).
4. Framework guides share a common pattern: prerequisites → auth → SDK setup → tool wrappers → example prompts → error table → troubleshooting.
5. CLAUDE.md files are navigation files, not end-user docs — focus on "what changed and why" in Recent Changes, not "how to use."
