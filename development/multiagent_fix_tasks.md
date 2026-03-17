# Multi-Agent Fixes: Risk Isolation & Agent-Scoped Architecture

## Task Checklist

- [ ] **Task 1: Verify & Fix Migration State** — Check alembic migrations 009/011/012 are applied
- [x] **Task 2: Refactor RiskManager to Use Agent's Risk Profile** — `_build_risk_limits()` uses agent.risk_profile when present; `validate_order()` accepts `agent: Agent | None` instead of `risk_profile_override`
- [x] **Task 3: Fix Daily Loss Check — Use Agent's Starting Balance** — `_check_daily_loss()` accepts `starting_balance_override`; `validate_order()` passes agent.starting_balance
- [x] **Task 4: Fix Rate Limiting — Scope to Agent** — `_check_rate_limit()` uses agent_id in Redis key when agent is present
- [x] **Task 5: Add Agent-Level Risk Profile API Endpoints** — `GET/PUT /api/v1/agents/{id}/risk-profile` endpoints added
- [x] **Task 6: Fix PUT /account/risk-profile to Route Through Agent** — When X-Agent-Id header present, writes to agent.risk_profile instead of account
- [x] **Task 7: Fix GET /account/info to Show Agent Risk Profile** — `_build_risk_profile_info()` uses agent.risk_profile; returns agent.starting_balance
- [x] **Task 8: Update trading.py:place_order to Pass Agent Object** — Passes `agent=agent` instead of `risk_profile_override`
- [x] **Task 9: Update Tests** — Added agent-scoped tests for risk profile, daily loss, rate limit, get_risk_limits
- [ ] **Task 10: Frontend — Verify Risk Settings Work Per-Agent** — Backend changes should work transparently with existing X-Agent-Id header injection
- [x] **Task 11: Fix get_risk_limits() and check_daily_loss() Public Methods** — Both accept optional `agent` parameter
