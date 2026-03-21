---
type: research-report
title: "Agent Memory & Learning System — CTO Strategy Report"
status: active
phase: agent-memory
tags:
  - research
  - agent-memory
---

# Agent Memory & Learning System — CTO Strategy Report

**Date:** 2026-03-21 | **Audience:** CTO / Operations & Dev Team
**Subject:** How to log, track, and improve our 16 Claude Code sub-agents

---

## 1. Current State Assessment

### What We Have Today

| Aspect | Status | Detail |
|--------|--------|--------|
| **16 deployed agents** | Active | `.claude/agents/` — all have frontmatter, tools, model assignments |
| **Memory enabled** | 4 of 16 | `code-reviewer`, `context-manager`, `planner`, `security-reviewer` use `memory: project` |
| **Hooks** | 1 hook | PostToolUse echo reminder after Write/Edit — no logging |
| **Code review reports** | 10 reports | `development/code-reviews/` — includes 4 CRITICAL security fixes |
| **Development context** | Maintained | `development/context.md` — 22 milestones tracked |
| **Pipeline logging** | None | 6 documented pipelines, zero execution tracking |
| **Starter kit** | Ready | `claude-code-starter-kit/` — 16 agents, 5 skills, 3 rules, portable |

### The Gap

Agents work well but operate as **stateless workers** — they don't learn from past runs, can't see what other agents discovered, and we have no metrics on their effectiveness. We're leaving significant value on the table.

---

## 2. Options Analysis

### Option A: Claude Code Native Memory (Zero Infrastructure)

**How it works:** Each agent gets a persistent memory directory (`.claude/agent-memory/<name>/MEMORY.md`) that survives across conversations. Agents read memory at startup, write learnings when they finish.

**What to do:**
- Enable `memory: project` on all 16 agents (currently only 4)
- Seed each agent's MEMORY.md with domain patterns
- Add memory protocols to agent prompts ("read memory before starting, update when done")
- Memory is git-committed — team-shared, version-controlled

**Pros:**
- Zero external infrastructure
- Built into Claude Code — no custom code needed
- Git-tracked = auditable, rollbackable
- Agents immediately benefit from past learnings

**Cons:**
- 200-line cap on MEMORY.md (forces aggressive curation)
- No semantic search ("find similar issues")
- No cross-agent memory sharing (each agent reads its own)
- Passive — Claude decides what to save (no guaranteed logging)

**Cost:** $0 | **Timeline:** 1 day | **Value:** High

---

### Option B: Structured File-Based Logging (Low Infrastructure)

**How it works:** PostToolUse and Stop hooks capture agent activity as JSON events in an append-only log file. Analysis scripts query the log with `jq`.

**Implementation:**

```
.claude/settings.json hooks:
  PostToolUse (Write|Edit) → /scripts/log-agent-activity.sh
  Stop → /scripts/agent-run-summary.sh

Output:
  development/agent-activity-log.jsonl (append-only)
  development/agent-runs/<date>/summary.md (per-run reports)
```

**Event schema:**
```json
{
  "timestamp": "2026-03-21T10:30:00Z",
  "agent": "code-reviewer",
  "event": "issue_found",
  "severity": "warning",
  "file": "src/api/routes.py",
  "line": 42,
  "issue": "missing input validation",
  "session": "abc123"
}
```

**Queryable with standard tools:**
```bash
# Most common issues
jq 'select(.event=="issue_found") | .issue' agent-activity-log.jsonl | sort | uniq -c | sort -rn

# Agent run count by week
jq 'select(.event=="complete")' agent-activity-log.jsonl | jq -s 'group_by(.agent) | map({agent: .[0].agent, runs: length})'
```

**Pros:**
- Minimal infrastructure (shell scripts + JSONL file)
- Human-readable + machine-queryable
- Git-versioned audit trail
- Works with existing hook system

**Cons:**
- Not scalable beyond ~1M events
- No semantic search
- Requires custom parsing scripts
- No real-time dashboards

**Cost:** $0 | **Timeline:** 3 days | **Value:** High

---

### Option C: PostgreSQL Activity Database (Medium Infrastructure)

**How it works:** Agent activity logged to your existing PostgreSQL instance. SQL queries for trend analysis, dashboards, cross-agent patterns.

**Schema:**
```sql
CREATE TABLE agent_activity (
  id BIGSERIAL PRIMARY KEY,
  agent_name TEXT NOT NULL,
  timestamp TIMESTAMPTZ DEFAULT NOW(),
  session_id UUID,
  event_type TEXT,  -- 'start', 'tool_use', 'issue_found', 'complete'
  severity TEXT,
  file_path TEXT,
  issue_description TEXT,
  metadata JSONB
);
```

**Example queries:**
```sql
-- Recurring issues (what should agents learn?)
SELECT issue_description, COUNT(*) as frequency
FROM agent_activity WHERE event_type='issue_found'
GROUP BY issue_description ORDER BY frequency DESC LIMIT 10;

-- Agent accuracy trend (are they improving?)
SELECT agent_name, DATE(timestamp),
  COUNT(CASE WHEN metadata->>'feedback' = 'kept' THEN 1 END) as kept,
  COUNT(CASE WHEN metadata->>'feedback' = 'rejected' THEN 1 END) as rejected
FROM agent_activity GROUP BY agent_name, DATE(timestamp);
```

**Pros:**
- Scalable (millions of events)
- Rich SQL queries
- Uses existing infrastructure (you already run PostgreSQL)
- Can add pgvector later for semantic search

**Cons:**
- Requires migration + schema management
- Hook scripts need DB connection
- Additional operational burden
- Overkill if <1000 agent runs/month

**Cost:** $0-20/month | **Timeline:** 2 weeks | **Value:** Medium-High

---

### Option D: MCP Memory Server (Knowledge Graph)

**How it works:** Run an MCP server that provides memory tools to agents. Agents store/query a knowledge graph (entities, relations, observations).

**Configuration:**
```json
// .mcp.json
{
  "mcpServers": {
    "memory": {
      "type": "stdio",
      "command": "npx @anthropic/mcp-servers-memory"
    }
  }
}
```

**Agent usage:**
```
Agent: "Store that validation is missing in POST endpoints"
→ MCP: CREATE entity "pattern:missing-validation"
→ Storage: PostgreSQL / Neo4j / filesystem

[Next run]
Agent: "Query patterns about endpoint validation"
→ MCP: SEARCH "validation"
→ Returns: 5 previous validation issues, 12 total occurrences
```

**Available servers:**
| Server | Storage | Maturity |
|--------|---------|----------|
| `@anthropic/mcp-servers-memory` | Filesystem | Reference impl |
| `neo4j-labs/agent-memory` | Neo4j | Production-grade |
| `mcp-neo4j-memory-server` | Neo4j | Community |
| Graphiti (Zep) | Neo4j | Temporal-aware |

**Pros:**
- Standard protocol (MCP is becoming industry norm)
- Agents use memory natively as tool calls
- Knowledge graph captures relationships
- Self-hosted or cloud

**Cons:**
- Requires running external MCP server process
- Adds latency per memory operation (100-200ms per tool call)
- Immature ecosystem — not all servers are production-ready
- Additional operational burden

**Cost:** $0-500/month (depending on backend) | **Timeline:** 3 weeks | **Value:** Medium

---

### Option E: Mem0 (Open-Source Agent Memory Framework)

**How it works:** Mem0 is a dedicated memory layer for AI agents. Auto-extracts salient information from conversations, stores as vectors + graph + key-value, retrieves semantically.

**Architecture:**
```
Agent interaction → Mem0 extracts facts → Store in Vector DB + Graph DB
Next task → Agent queries Mem0 → Gets ranked, relevant memories
```

**Claims:** 26% accuracy improvement, 91% lower p95 latency vs naive RAG, 90% token savings.

**Pros:**
- Purpose-built for agent memory
- Auto-deduplication and consolidation
- Temporal awareness
- MIT license, well-maintained

**Cons:**
- Requires external infra (PostgreSQL + Qdrant/Weaviate)
- Not integrated with Claude Code (needs custom hooks)
- Additional LLM calls for extraction (cost)
- Operational burden (monitor vector DB + graph DB)

**Cost:** $200-400/month | **Timeline:** 1 month | **Value:** Medium-Low (overkill for current scale)

---

### Option F: Obsidian as Knowledge Base

**How it works:** Use Obsidian vault for human-curated agent knowledge. Link notes with `[[wikilinks]]`, tag with metadata, search with full-text.

**Pros:**
- Excellent for human-curated knowledge
- Visual graph view of relationships
- Plugin ecosystem (AI integrations, templates)
- Local-first, markdown-based

**Cons:**
- Manual curation (not automated)
- No programmatic API for agents to query
- Requires separate app
- Not designed for machine-to-machine communication

**Verdict:** Good for CTO's personal knowledge base about agents, NOT for agent self-improvement.

---

## 3. Comparison Matrix

| Criterion | A: Native Memory | B: File Logging | C: PostgreSQL | D: MCP Server | E: Mem0 | F: Obsidian |
|-----------|:-:|:-:|:-:|:-:|:-:|:-:|
| **Setup time** | 1 day | 3 days | 2 weeks | 3 weeks | 1 month | 1 week |
| **Monthly cost** | $0 | $0 | $0-20 | $0-500 | $200-400 | $0 |
| **Infrastructure** | None | Scripts | Existing DB | New service | 3 services | Desktop app |
| **Agent self-learning** | Yes | No | No | Yes | Yes | No |
| **Queryable metrics** | No | Yes (jq) | Yes (SQL) | Yes (graph) | Yes (semantic) | Manual |
| **Cross-agent sharing** | Limited | Yes | Yes | Yes | Yes | Manual |
| **Semantic search** | No | No | With pgvector | Yes | Yes | Plugin |
| **Scales to 10K runs** | Yes | Slow | Yes | Yes | Yes | No |
| **Team-friendly** | Git | Git | Dashboard | API | API | Vault sync |
| **Feedback loops** | Manual | Script | SQL | Built-in | Built-in | Manual |

---

## 4. Recommendation: Phased Hybrid Approach

Start simple, add complexity only when you need it.

### Phase 1: Native Memory Expansion (Week 1)

**Goal:** Every agent remembers and learns.

**Actions:**
1. Enable `memory: project` on ALL 16 agents (currently 4)
2. Create `.claude/agent-memory/<name>/MEMORY.md` for each agent
3. Seed with domain-specific patterns:
   - `code-reviewer`: common issues found, validation checklist, security patterns
   - `backend-developer`: project conventions, async patterns, import order
   - `frontend-developer`: component patterns, hook conventions, Tailwind usage
   - `test-runner`: test patterns, fixture usage, common test failures
   - etc.
4. Add memory protocol to each agent's system prompt:
   ```
   Before starting: Read your MEMORY.md for patterns from previous runs.
   After completing: Update MEMORY.md with new patterns discovered.
   ```
5. Add `.claude/agent-memory-local/` to `.gitignore`

**Deliverable:** All 16 agents persist learning across conversations.

---

### Phase 2: Structured Activity Logging (Weeks 2-3)

**Goal:** Full audit trail of all agent activity.

**Actions:**
1. Create `scripts/log-agent-activity.sh`:
   ```bash
   #!/bin/bash
   # Receives hook JSON from stdin, appends structured event to JSONL
   HOOK_INPUT=$(cat)
   TOOL=$(echo "$HOOK_INPUT" | jq -r '.tool_name // "unknown"')
   TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
   echo "{\"timestamp\":\"$TIMESTAMP\",\"tool\":\"$TOOL\",\"input\":$(echo $HOOK_INPUT | jq -c '.tool_input // {}')}" \
     >> development/agent-activity-log.jsonl
   exit 0
   ```

2. Create `scripts/agent-run-summary.sh`:
   ```bash
   #!/bin/bash
   # Runs on agent Stop, creates markdown summary
   DATE=$(date +%Y-%m-%d)
   mkdir -p "development/agent-runs/$DATE"
   git diff HEAD --stat > "development/agent-runs/$DATE/changes.txt"
   ```

3. Update `.claude/settings.json` hooks:
   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Write|Edit|Bash",
           "hooks": [{ "type": "command", "command": "bash scripts/log-agent-activity.sh" }]
         }
       ]
     }
   }
   ```

4. Create `scripts/analyze-agent-metrics.sh` for weekly reporting:
   ```bash
   #!/bin/bash
   echo "=== Agent Activity Summary ==="
   jq -s 'group_by(.agent) | map({agent: .[0].agent, events: length})' \
     development/agent-activity-log.jsonl
   ```

**Deliverable:** Queryable activity log + weekly metrics.

---

### Phase 3: Feedback Loop & Agent Improvement (Month 2)

**Goal:** Closed-loop learning — agents improve from tracked outcomes.

**Actions:**
1. Add feedback capture to `/review-changes` skill:
   - After agent completes review, prompt: "Accept findings? [keep/reject/modify]"
   - Log feedback to `agent-activity-log.jsonl`

2. Create `/analyze-agents` skill:
   - Reads activity log
   - Identifies recurring false positives per agent
   - Suggests agent prompt updates
   - Generates improvement report

3. Track accuracy metrics:
   ```
   Accuracy = kept_findings / (kept_findings + rejected_findings)
   Goal: >85% accuracy per agent
   ```

4. Automate agent prompt updates:
   - If `code-reviewer` has >20% false positive rate on "N+1 queries"
   - Update its MEMORY.md with clarification: "Check for memoization before flagging"

**Deliverable:** Measurable agent improvement over time.

---

### Phase 4: PostgreSQL + Dashboard (Month 3, Optional)

**Goal:** Team-wide visibility into agent performance.

**Trigger:** Only pursue if file-based logging becomes slow (>10K events) or team needs dashboards.

**Actions:**
1. Add `agent_activity` table to existing PostgreSQL
2. Create Alembic migration
3. Modify logging scripts to write to DB
4. Add Grafana dashboard for agent metrics:
   - Runs per day per agent
   - Issue frequency trends
   - Accuracy over time
   - Token usage

**Deliverable:** Production dashboard for agent ops.

---

### DO NOT PURSUE (Yet)

| Option | Reason |
|--------|--------|
| **Mem0** | Overkill — requires 3 external services for what native memory + JSONL handles |
| **Vector databases** (Chroma, Qdrant) | Semantic search not needed yet — keyword + SQL is sufficient |
| **Neo4j knowledge graph** | Relationship queries not valuable until >100K events |
| **Obsidian** | Good for personal notes, not for automated agent learning |

**Revisit in 6 months** if you hit >10K agent runs/month or need semantic search.

---

## 5. Implementation Priority Matrix

```
                    HIGH VALUE
                       |
     Phase 1           |    Phase 3
     Native Memory     |    Feedback Loops
     (1 day, $0)       |    (2 weeks, $0)
                       |
  LOW EFFORT --------- + --------- HIGH EFFORT
                       |
     Phase 2           |    Phase 4
     File Logging      |    PostgreSQL + Dashboard
     (3 days, $0)      |    (2 weeks, $0-20/mo)
                       |
                    LOW VALUE
```

---

## 6. Quick Reference: Memory Scope Options

For each agent in `.claude/agents/<name>.md`:

```yaml
memory: project   # Git-committed, team-shared — USE FOR: code-reviewer, planner, security-reviewer
memory: user      # Machine-local, personal — USE FOR: agents with individual workflow preferences
memory: local     # Machine-local, not in git — USE FOR: experimental or sensitive learnings
```

**Recommendation:** Use `memory: project` for all 16 agents. Team learning > individual learning for this project.

---

## 7. Expected Outcomes (90-Day)

| Metric | Before | After Phase 1 | After Phase 3 |
|--------|--------|---------------|---------------|
| Agent false positive rate | Unknown | Tracked | <15% |
| Recurring issues caught | Some | Most (via memory) | >90% |
| Agent improvement cycle | Manual | Semi-auto | Auto-suggested |
| Audit trail | Code reviews only | Full activity log | Full + metrics |
| Cross-agent learning | None | Via git (memory) | Structured feedback |
| Time to onboard new agent | ~2 hours | ~30 min (templates + memory) | ~15 min |

---

## 8. Files to Create/Modify

### Phase 1 (Native Memory)
```
MODIFY: .claude/agents/*.md (add memory: project to all 12 missing agents)
CREATE: .claude/agent-memory/<name>/MEMORY.md (16 files, seeded with domain patterns)
MODIFY: .gitignore (add .claude/agent-memory-local/)
```

### Phase 2 (Logging)
```
CREATE: scripts/log-agent-activity.sh
CREATE: scripts/agent-run-summary.sh
CREATE: scripts/analyze-agent-metrics.sh
MODIFY: .claude/settings.json (add logging hooks)
CREATE: development/agent-activity-log.jsonl (auto-created by scripts)
```

### Phase 3 (Feedback)
```
MODIFY: .claude/skills/review-changes/SKILL.md (add feedback capture)
CREATE: .claude/skills/analyze-agents/SKILL.md (new analysis skill)
MODIFY: .claude/agent-memory/*/MEMORY.md (auto-updated by feedback)
```

---

## 9. Decision Required

**Recommended path:** Phases 1 + 2 immediately (1 week total, $0 cost).

Phase 3 after 30 days of data collection. Phase 4 only if team needs dashboards.

**Alternative:** If you want semantic search from day 1, go with MCP Memory Server (Option D) instead of file logging. Adds 3 weeks and operational complexity but provides knowledge graph queries.

---

*Report prepared for AiTradingAgent Platform — Operations & Dev Team*
*Next review: April 21, 2026 (post-Phase 2 assessment)*
