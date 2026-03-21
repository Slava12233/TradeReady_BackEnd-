# Execution Guide: Agent Memory & Learning System

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Phase 1: Native Memory Expansion (Week 1)

**Parallel Group 1** (no dependencies):
- Task 01: Enable `memory: project` on all agents → `context-manager`
- Task 08: Update .gitignore → `context-manager`

**Parallel Group 2** (after Task 01):
- Task 02: Seed MEMORY.md — quality gate agents → `context-manager`
- Task 03: Seed MEMORY.md — security agents → `context-manager`
- Task 04: Seed MEMORY.md — infrastructure agents → `context-manager`
- Task 05: Seed MEMORY.md — development agents → `context-manager`
- Task 06: Seed MEMORY.md — research agents → `context-manager`

**Sequential** (after Tasks 02-06):
- Task 07: Add memory protocol to all agent prompts → `context-manager`

### Phase 2: Structured Activity Logging (Weeks 2-3)

**Parallel Group 3** (no Phase 1 dependency):
- Task 09: Create log-agent-activity.sh → `backend-developer`
- Task 10: Create agent-run-summary.sh → `backend-developer`

**Sequential** (after Task 09):
- Task 11: Create analyze-agent-metrics.sh → `backend-developer`

**Sequential** (after Tasks 09 + 10):
- Task 12: Update settings.json with hooks → `context-manager`

### Phase 3: Feedback Loop (Month 2)

**Sequential** (after Tasks 09-11):
- Task 13: Create /analyze-agents skill → `backend-developer`

**Sequential** (after Task 12):
- Task 14: Update /review-changes with feedback → `backend-developer`

## Post-Task Checklist

After each task completes:
- [ ] code-reviewer agent validates the changes
- [ ] test-runner agent runs relevant tests
- [ ] context-manager agent logs what changed
- [ ] If settings changed: verify Claude Code picks up new config

## Verification

After Phase 1 complete:
- [ ] All 16 agents have `memory: project` in frontmatter
- [ ] 16 MEMORY.md files exist in `.claude/agent-memory/`
- [ ] All agents have "Memory Protocol" section in their prompts
- [ ] `.gitignore` excludes `.claude/agent-memory-local/`

After Phase 2 complete:
- [ ] `scripts/log-agent-activity.sh` runs without errors
- [ ] `scripts/agent-run-summary.sh` creates summary files
- [ ] `scripts/analyze-agent-metrics.sh` produces readable output
- [ ] Settings hooks trigger on Write/Edit/Bash tool use
- [ ] `development/agent-activity-log.jsonl` gets populated on next agent run

After Phase 3 complete:
- [ ] `/analyze-agents` skill is invocable and produces reports
- [ ] `/review-changes` captures user feedback
- [ ] Feedback appears in JSONL log
