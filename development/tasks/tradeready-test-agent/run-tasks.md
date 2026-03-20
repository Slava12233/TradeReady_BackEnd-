# Execution Guide: TradeReady Platform Testing Agent (V1)

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Parallel Execution Groups

**Group A (start immediately):**
- Task 1: Project scaffolding → then Task 2: Config (sequential)
- Task 3: Research (parallel with Tasks 1-2)

**Group B (after Group A):**
- Task 4: SDK tools
- Task 5: MCP tools
- Task 6: REST tools
- Task 7: Output models (only needs Task 1, can start early)

**Group C (after Group B + Task 8):**
- Task 9: Smoke test
- Task 10: Trading workflow
- Task 11: Backtest workflow
- Task 12: Strategy workflow

### Sequential Chains

Task 13 (CLI) → Task 14 (tests) → Task 15 (review) → Task 16 (E2E) → Task 17 (docs) → Task 18 (context)

## Post-Task Checklist

After each code-writing task completes:
- [ ] code-reviewer agent validates the changes
- [ ] test-runner agent runs relevant tests
- [ ] context-manager agent logs what changed

After all tasks complete:
- [ ] security-auditor reviews the full agent package (handles API keys, external API calls)
- [ ] deploy-checker validates the package is production-ready
