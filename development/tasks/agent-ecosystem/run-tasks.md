# Agent Ecosystem — Execution Guide

## Execution Order

Tasks must be executed in dependency order. Within each group, tasks can run in parallel.

---

### Phase 1: Agent Core

#### Group 1 — Foundation (no dependencies, start immediately)
| Task | Agent | Description |
|------|-------|-------------|
| **01** | `backend-developer` | Database models for all 10 tables |
| **34** | `backend-developer` | Pydantic output models for ecosystem |

> **Run in parallel.** Both are independent.

#### Group 2 — Migration (depends on Group 1)
| Task | Agent | Description |
|------|-------|-------------|
| **02** | `migration-helper` | Alembic migration for all 10 tables |

> **Sequential.** Must wait for Task 01.

#### Group 3 — Repositories + Config (depends on Group 2)
| Task | Agent | Description |
|------|-------|-------------|
| **03** | `backend-developer` | 10 database repositories |
| **19** | `backend-developer` | Config extensions |

> **Run in parallel.** Both depend on models/migration, not on each other.

#### Group 4 — Core Systems (depends on Group 3)
| Task | Agent | Description |
|------|-------|-------------|
| **04** | `test-runner` | Repository unit tests |
| **05** | `backend-developer` | Conversation session manager |
| **09** | `backend-developer` | Memory store + Postgres implementation |
| **16** | `backend-developer` | Enhanced tools (reflect_on_trade, review_portfolio) |

> **Run in parallel.** All depend only on repos (Task 03).

#### Group 5 — System Extensions (depends on Group 4)
| Task | Agent | Description |
|------|-------|-------------|
| **06** | `backend-developer` | Conversation history + context builder |
| **07** | `backend-developer` | Intent router |
| **10** | `backend-developer` | Redis memory cache |
| **17** | `backend-developer` | Enhanced tools (scan, journal, feedback) |

> **Run in parallel.** 06+07 depend on 05, 10 on 09, 17 on 16.

#### Group 6 — Retrieval + Server (depends on Group 5)
| Task | Agent | Description |
|------|-------|-------------|
| **11** | `backend-developer` | Memory retrieval engine |
| **13** | `backend-developer` | Agent server (persistent process) |

> **Run in parallel.** 11 depends on 09+10, 13 depends on 05+09.

#### Group 7 — User-Facing + Tests (depends on Group 6)
| Task | Agent | Description |
|------|-------|-------------|
| **08** | `test-runner` | Conversation system tests |
| **12** | `test-runner` | Memory system tests |
| **14** | `backend-developer` | Celery beat tasks |
| **15** | `backend-developer` | CLI chat interface |
| **18** | `test-runner` | Enhanced tools tests |

> **Run in parallel.** Multiple independent test suites + CLI.

#### Group 8 — Phase 1 Integration (depends on Group 7)
| Task | Agent | Description |
|------|-------|-------------|
| **20** | `test-runner` | Phase 1 integration test |

> **Sequential.** Depends on all Phase 1 component tests.

---

### Phase 2: Trading Intelligence

#### Group 9 — Permission System (depends on Group 3)
| Task | Agent | Description |
|------|-------|-------------|
| **21** | `backend-developer` | Roles and capabilities |

> **Can start as soon as Task 03 is done** (parallel with Phase 1 Groups 4-8).

#### Group 10 — Permission Extensions (depends on Group 9)
| Task | Agent | Description |
|------|-------|-------------|
| **22** | `backend-developer` | Budget enforcement |

> **Sequential.** Depends on Task 21.

#### Group 11 — Permission Enforcement (depends on Group 10)
| Task | Agent | Description |
|------|-------|-------------|
| **23** | `backend-developer` | Enforcement middleware + audit log |

> **Sequential.** Depends on Tasks 21+22.

#### Group 12 — Permission Validation (depends on Group 11)
| Task | Agent | Description |
|------|-------|-------------|
| **24** | `security-reviewer` | Security review |
| **25** | `test-runner` | Permission system tests |

> **Run in parallel.** Both depend on Tasks 21-23.

#### Group 13 — Trading Loop (depends on Groups 8 + 11)
| Task | Agent | Description |
|------|-------|-------------|
| **26** | `backend-developer` | Main loop + signal generator |

> **Sequential.** Depends on Task 13 (server) + Task 23 (permissions).

#### Group 14 — Trading Extensions (depends on Group 13)
| Task | Agent | Description |
|------|-------|-------------|
| **27** | `backend-developer` | Execution engine + position monitor |
| **29** | `ml-engineer` | Strategy performance monitoring |

> **Run in parallel.** Both depend on Task 26.

#### Group 15 — Trading Completions (depends on Group 14)
| Task | Agent | Description |
|------|-------|-------------|
| **28** | `backend-developer` | Trading journal system |
| **30** | `ml-engineer` | A/B testing framework |

> **Run in parallel.** 28 depends on 26+27, 30 depends on 29.

#### Group 16 — Trading Tests (depends on Group 15)
| Task | Agent | Description |
|------|-------|-------------|
| **31** | `test-runner` | Trading loop + journal tests |
| **32** | `test-runner` | Strategy management + A/B tests |

> **Run in parallel.** Independent test suites.

#### Group 17 — Phase 2 Integration (depends on Group 16 + 12)
| Task | Agent | Description |
|------|-------|-------------|
| **33** | `test-runner` | Phase 2 integration test |

> **Sequential.** Depends on all Phase 2 component tests.

#### Group 18 — Finalization (depends on Group 17 + 8)
| Task | Agent | Description |
|------|-------|-------------|
| **35** | `doc-updater` | Documentation + CLAUDE.md updates |

> **Sequential.** All code must be complete.

#### Group 19 — Context Update (FINAL)
| Task | Agent | Description |
|------|-------|-------------|
| **36** | `context-manager` | Update development context |

> **FINAL TASK.** Always runs last.

---

## Parallel Execution Summary

```
Time ──────────────────────────────────────────────────────────►

Group 1:  [01, 34]
Group 2:  ........[02]
Group 3:  ............[03, 19]
Group 4:  ..................[04, 05, 09, 16]
Group 5:  ........................[06, 07, 10, 17]
Group 6:  ..............................[11, 13]
Group 7:  ....................................[08, 12, 14, 15, 18]
Group 8:  ............................................[20]

Group 9:  ..................[21]          ← can overlap with Phase 1 Groups 4-8
Group 10: ......................[22]
Group 11: .........................[23]
Group 12: .............................[24, 25]
Group 13: ............................................[26]
Group 14: ................................................[27, 29]
Group 15: ....................................................[28, 30]
Group 16: ........................................................[31, 32]
Group 17: ............................................................[33]
Group 18: ................................................................[35]
Group 19: ....................................................................[36]
```

## Quick Start

1. Start with Tasks **01** and **34** (both `backend-developer`, no dependencies)
2. Then Task **02** (`migration-helper`)
3. Then Tasks **03** and **19** (both `backend-developer`)
4. From here, many tasks can run in parallel — follow the group ordering above

## Post-Change Pipeline Reminder

After completing each task, the standard pipeline should run:
```
code-reviewer → test-runner → context-manager
```

However, for efficiency during this task board, we defer the full pipeline to the integration test tasks (20, 33) and the final documentation/context tasks (35, 36).
