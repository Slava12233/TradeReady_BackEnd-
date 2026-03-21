---
task_id: 27
title: "Update code-reviewer output format"
type: task
agent: context-manager
phase: 9
depends_on: [12, 13, 14, 15]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - .claude/agents/code-reviewer.md
tags:
  - task
  - obsidian
  - agent-update
  - code-review
---

# Update code-reviewer output format

## Assigned Agent: `context-manager`

## Objective

Add a note to the code-reviewer agent's system prompt instructing it to include Obsidian-compatible YAML frontmatter when creating new review files.

## Context

Future code reviews will be Dataview-queryable from creation. The additional frontmatter does not break any existing parsing -- agents write to files with the Write tool; no code parses review files programmatically.

## Files to Modify

- `.claude/agents/code-reviewer.md`

## Change

In the "Output Format" or "Report Structure" section of the prompt, add:

```
When creating a new review file in `development/code-reviews/`, include this YAML frontmatter at the top:
---
type: code-review
date: YYYY-MM-DD
reviewer: code-reviewer
verdict: <PASS | PASS WITH WARNINGS | NEEDS FIXES>
scope: <brief scope descriptor>
tags:
  - review
  - <relevant module tags>
---
```

## Acceptance Criteria

- [ ] `.claude/agents/code-reviewer.md` includes frontmatter instructions
- [ ] Frontmatter format matches the standard defined in Task 04
- [ ] Existing agent instructions are preserved
- [ ] No agent source code is modified (only the prompt markdown)

## Estimated Complexity

Low
