---
task_id: 32
title: "Implement memory-driven learning loop"
type: task
agent: "backend-developer"
phase: 4
depends_on: []
status: "completed"
priority: "medium"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/trading/journal.py", "agent/conversation/context.py"]
tags:
  - task
  - memory
  - learning
---

# Task 32: Memory-driven learning loop

## Assigned Agent: `backend-developer`

## Objective
Enhance `TradingJournal` to save structured episodic and procedural memories after each trade, and `ContextBuilder` to retrieve relevant past learnings before each trade decision.

## Post-Trade (TradingJournal)
1. Save EPISODIC: entry/exit prices, PnL, reasoning, regime at time of trade
2. Save PROCEDURAL: "pattern X worked in regime Y" or "avoid Z when volume is low"
3. Reinforce matching past memories (builds confidence)

## Pre-Trade (ContextBuilder)
1. Retrieve top 5 PROCEDURAL memories for current symbol + regime
2. Include in context: "Past experience: [memory summaries]"
3. This gives the LLM daily analysis real learning from past trades

## Acceptance Criteria
- [ ] Each trade produces EPISODIC + PROCEDURAL memories
- [ ] ContextBuilder retrieves relevant memories before analysis
- [ ] Memory reinforcement tracked via `times_reinforced` field
- [ ] Tests verify memory creation and retrieval cycle

## Estimated Complexity
Medium — enhancing existing journal and context systems.
