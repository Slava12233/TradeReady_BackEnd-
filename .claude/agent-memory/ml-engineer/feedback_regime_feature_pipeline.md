---
name: regime_feature_pipeline
description: How to add a new feature to the regime classifier — the 3-file pipeline pattern and gotchas learned from Task 08 (volume_ratio)
type: feedback
---

Adding a new feature to the regime classifier requires touching exactly 3 files in order:

**1. `agent/strategies/regime/labeler.py`**
- Add a `_<feature>_series(arr, period) -> np.ndarray` helper that returns a same-length float array with `nan` for warm-up positions.
- Extract the raw data from candle dicts in `generate_training_data()` (e.g., `volumes = np.array([float(c.get("volume", 0.0)) for c in candles])`).
- Call the helper and add the result as a new column to `features_df`.
- Update the docstring "Features per candle" list.

**2. `agent/strategies/regime/classifier.py`**
- Append the new feature name to `self._feature_names` in `__init__`. The list order must exactly match the column order in `labeler.generate_training_data()`.
- Update the "N-feature input vector" count in the module docstring and the `train()` / `predict()` docstrings.
- No other changes needed — `RegimeSwitcher.detect_regime()` calls `generate_training_data()` and passes the full row to `clf.predict()` which selects by column name automatically.

**3. `agent/tests/test_regime.py`**
- Update `test_feature_columns_present` — add new name to the expected set.
- Update `test_feature_set_matches_platform_indicators` — add new name to expected set.
- Update the empty-DataFrame fixture in `test_train_raises_without_data` — add new column name.
- Add `test_feature_count_is_N` to lock in the count.

**Why:** The switcher does NOT need changes because it calls `generate_training_data` → passes the full feature row to `clf.predict()` which slices by `_feature_names`. The new column is transparently picked up.

**Gotcha — pre-existing `_print_evaluation` import failure in `test_regime.py`:**
The test imports `_print_evaluation` from `classifier.py` but the live code only had `_log_evaluation`. This caused a collection error that silently blocked all tests in `test_regime.py`. Fixed in Task 08 by adding `_print_evaluation` as a human-readable print-to-stdout function. Future tasks: if tests in `test_regime.py` fail to collect, check for missing imports at the top of the test file first.

**How to apply:** Follow this 3-file pattern for any future regime feature addition. Always run `pytest agent/tests/test_regime*.py` after each file is changed to catch issues early.
