# Training Module

<!-- last-updated: 2026-03-19 -->

> Training run observation — tracking, aggregation, and learning curves for RL/Gym training.

## What This Module Does

Provides the backend bridge between the Gymnasium wrapper package (STR-3) and the frontend UI (STR-UI-1). External RL training processes register runs, report episode results, and query learning curves through REST endpoints. The module aggregates statistics and computes smoothed learning curves for visualization.

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package marker |
| `tracker.py` | `TrainingRunService` — register, record episodes, complete, learning curves, comparison |

## Related Files (Outside This Module)

| File | Purpose |
|------|---------|
| `src/database/models.py` | ORM models: `TrainingRun`, `TrainingEpisode` |
| `src/database/repositories/training_repo.py` | `TrainingRunRepository` — all DB access for training tables |
| `src/api/schemas/training.py` | Pydantic v2 request/response schemas |
| `src/api/routes/training.py` | 7 REST endpoints under `/api/v1/training` |
| `src/dependencies.py` | `TrainingRunRepoDep`, `TrainingRunServiceDep` DI aliases |

## API Endpoints (7)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/training/runs` | Register new training run |
| POST | `/training/runs/{id}/episodes` | Report episode result |
| POST | `/training/runs/{id}/complete` | Mark run complete |
| GET | `/training/runs` | List all training runs |
| GET | `/training/runs/{id}` | Full detail + learning curve + episodes |
| GET | `/training/runs/{id}/learning-curve` | Learning curve with smoothing |
| GET | `/training/compare` | Compare multiple runs |

## Dependencies

- `src.database.repositories.training_repo` — all DB access
- `src.utils.exceptions` — error handling

## Gotchas

- Training runs are registered by external Gym clients, not created internally
- `run_id` is client-provided (UUID), not server-generated
- Learning curve smoothing uses a rolling mean window (configurable via query param)
- Episodes are appended incrementally; aggregate stats computed only on `complete()`
