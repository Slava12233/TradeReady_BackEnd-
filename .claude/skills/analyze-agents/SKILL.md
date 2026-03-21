---
name: analyze-agents
description: "Analyze agent activity logs, identify patterns, and suggest improvements. Reads JSONL activity log and agent memory files to generate an improvement report."
user-invocable: true
allowed-tools: Read, Write, Grep, Glob, Bash
---

# Analyze Agent Performance

Analyze agent activity and memory to identify improvement opportunities.

## Process

### 1. Gather activity data

Read the activity log:
```bash
cat development/agent-activity-log.jsonl 2>/dev/null | tail -500
```

Count total events:
```bash
wc -l development/agent-activity-log.jsonl 2>/dev/null
```

### 2. Analyze tool usage patterns

Using grep/bash, extract:
- Most frequently used tools
- Most frequently touched files
- Activity volume by day

If `jq` is available:
```bash
bash scripts/analyze-agent-metrics.sh
```

### 3. Read agent memory files

Scan all agent memory files for patterns:
```
Glob: .claude/agent-memory/*/MEMORY.md
```

For each memory file, assess:
- How many learnings are stored?
- Are any entries stale or contradictory?
- Are there patterns repeated across multiple agents?
- Is memory under the 100-line target?

### 4. Read recent code review reports

```
Glob: development/code-reviews/*.md
```

Extract:
- Recurring issue types (validation, async, security, etc.)
- False positive patterns (issues flagged but not real)
- Agent verdict distribution (PASS / PASS WITH WARNINGS / FAIL)

### 5. Generate improvement report

Create a report at `development/agent-analysis/report-{date}.md` with:

```markdown
# Agent Analysis Report — {date}

## Activity Summary
- Total events logged: {count}
- Active period: {date range}
- Most active tools: {top 5}
- Most touched files: {top 10}

## Memory Health
| Agent | Memory Lines | Entries | Stale? | Recommendations |
|-------|-------------|---------|--------|-----------------|
| code-reviewer | 45 | 12 | No | Add N+1 detection pattern |
| ... | ... | ... | ... | ... |

## Recurring Patterns
{List patterns that appear across multiple agents or runs}

## Suggested Memory Updates
{Specific changes to make to agent MEMORY.md files}

## Agent Prompt Improvements
{Suggested changes to agent system prompts based on activity analysis}

## False Positive Analysis
{Issues agents flagged that turned out to not be real problems}
```

### 6. Apply quick fixes

If any memory files:
- Exceed 100 lines → consolidate and archive old entries
- Have obviously stale entries → remove them
- Are missing patterns from code review reports → add them

## Rules
- Only suggest changes backed by data from the activity log or code reviews
- Do not modify agent system prompts directly — only suggest changes
- Memory updates should be actionable (not generic advice)
- Always create the report file, even if activity data is limited
- Create `development/agent-analysis/` directory if it doesn't exist
