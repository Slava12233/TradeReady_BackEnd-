---
paths:
  - "Frontend/**/*.{ts,tsx,js,jsx,css}"
---

# Frontend

**Stack:** Next.js 16, React 19, TypeScript, Tailwind CSS 4.2, pnpm.

See `Frontend/CLAUDE.md` for full conventions and component patterns.

## Commands

```bash
cd Frontend
pnpm dev              # Dev server at http://localhost:3000
pnpm build            # Production build (zero TS/lint errors required)
pnpm test             # Unit tests (vitest)
pnpm test:e2e         # Playwright E2E tests
pnpm dlx shadcn@latest add <component-name>  # Add shadcn/ui component
```

## SDK & Integrations

- **Python SDK** (`sdk/`): `AgentExchangeClient` (sync), `AsyncAgentExchangeClient` (async), `AgentExchangeWS` (streaming). See `sdk/CLAUDE.md`.
- **MCP Server** (`src/mcp/`): 58 trading tools over stdio transport. See `src/mcp/CLAUDE.md`.
