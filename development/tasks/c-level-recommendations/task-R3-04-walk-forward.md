---
task_id: R3-04
title: "Run 3-month walk-forward validation"
type: task
agent: "ml-engineer"
phase: 3
depends_on: ["R3-01"]
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["agent/strategies/walk_forward.py", "agent/strategies/walk_forward_results/"]
tags:
  - task
  - training
  - ml
  - validation
  - walk-forward
completed_at: "2026-03-23"
---

# Task R3-04: Run Walk-Forward Validation

## Assigned Agent: `ml-engineer`

## Objective
Run rolling walk-forward validation with 6-month train / 1-month test windows to detect overfitting.

## Acceptance Criteria
- [x] `python -m agent.strategies.walk_forward --strategy regime` completes
- [x] WFE (Walk-Forward Efficiency) >= 50%
- [x] If WFE < 50%: strategy needs retuning before deployment (flag as overfit)
- [x] Results saved to `agent/strategies/walk_forward_results/`

## Dependencies
- R3-01 (trained model) + R1-07 (12+ months data for rolling windows)

## Agent Instructions
1. Read `agent/strategies/CLAUDE.md` for walk-forward validation details
2. WFE < 50% triggers overfit warning — document but do not block
3. With 12 months of data, expect ~6 rolling windows

## Estimated Complexity
High — computationally intensive with multiple retrain cycles

## Results (2026-03-23)

### Implementation Notes
The walk-forward CLI (`walk_forward.py`) did not previously support `--strategy regime`. The following additions were made:
- Added `walk_forward_regime()` function that trains a fresh `RegimeClassifier` on each IS window and evaluates it on the OOS window
- Extended `_build_cli()` to accept `--strategy regime` as a third option
- Fixed candle pagination to use `start_time`/`end_time` query params (max 1000/request)
- Metric used: classifier **accuracy** (IS = 80% train split holdout; OOS = immediately following month)
- WFE = mean(OOS accuracy) / mean(IS accuracy)

### Walk-Forward Results
| Window | Period | IS Accuracy | OOS Accuracy |
|--------|--------|-------------|--------------|
| 0 | Jan–Jun 2024 train / Jul 2024 OOS | 99.88% | 99.57% |
| 1 | Feb–Jul 2024 train / Aug 2024 OOS | 99.65% | 97.30% |
| 2 | Mar–Aug 2024 train / Sep 2024 OOS | 99.54% | 96.92% |
| 3 | Apr–Sep 2024 train / Oct 2024 OOS | 99.31% | 96.03% |
| 4 | May–Oct 2024 train / Nov 2024 OOS | 99.43% | 92.95% |
| 5 | Jun–Nov 2024 train / Dec 2024 OOS | 99.43% | 99.29% |

**Summary:**
- Windows: **6/6 successful**
- Mean IS Accuracy: **99.54%**
- Mean OOS Accuracy: **97.01%**
- **Walk-Forward Efficiency (WFE): 97.46%**
- Threshold: 50.00%
- **Deployable: TRUE** (far exceeds threshold)

The classifier generalises strongly — OOS accuracy drops only ~2.5 pp from IS. No overfitting detected. Window 4 (Nov 2024 OOS) shows the lowest OOS accuracy (92.95%) due to sparse high_volatility labels in that month, which is expected for minority class regime transitions.

Report saved: `C:\Users\Shalom Boy\Desktop\AiTradingAgent\agent\strategies\walk_forward_results\regime_wf_report.json`

Command used:
```bash
PLATFORM_API_KEY=<key> PLATFORM_BASE_URL=http://localhost:8000 \
  python -m agent.strategies.walk_forward \
    --strategy regime \
    --data-start 2024-01-01T00:00:00Z \
    --data-end 2025-01-01T00:00:00Z \
    --train-months 6 \
    --oos-months 1 \
    --seed 42
```
