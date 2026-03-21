---
task_id: 30
title: "Code review and testing"
type: task
agent: code-reviewer, test-runner
phase: 10
depends_on: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files: []
tags:
  - task
  - obsidian
  - quality-gate
  - code-review
  - testing
---

# Code review and testing

## Assigned Agent: `code-reviewer` then `test-runner`

## Objective

Run the standard post-change pipeline across all modified files to ensure quality and correctness.

## Context

Mandatory quality gate per project standards. All new and modified files must pass validation.

## Checks

- [ ] All new files have valid YAML frontmatter (parseable by a YAML parser)
- [ ] No existing file functionality is broken
- [ ] No existing tests fail
- [ ] Obsidian config JSON is valid
- [ ] Wikilinks resolve to actual files (no broken links)
- [ ] Frontmatter fields are consistent across file types
- [ ] No CLAUDE.md file contains `[[wikilinks]]`

## Validation Scripts

```bash
# YAML frontmatter validity
python -c "
import yaml, glob
for f in glob.glob('development/**/*.md', recursive=True):
    if '.obsidian' in f: continue
    with open(f) as fh:
        content = fh.read()
    if content.startswith('---'):
        end = content.index('---', 3)
        yaml.safe_load(content[3:end])
        print(f'OK: {f}')
"

# Wikilink resolution
grep -roh '\[\[[^]]*\]\]' development/ --include='*.md' | sort -u

# No CLAUDE.md contamination
grep -r '\[\[' **/CLAUDE.md  # should return nothing
```

## Acceptance Criteria

- [ ] All YAML frontmatter is valid
- [ ] All JSON config files are valid
- [ ] No existing tests fail (`pytest tests/`)
- [ ] No broken wikilinks
- [ ] No wikilinks in CLAUDE.md files

## Estimated Complexity

Medium
