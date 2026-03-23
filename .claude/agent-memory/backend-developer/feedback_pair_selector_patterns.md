---
name: pair_selector_patterns
description: Patterns from implementing PairSelector with asyncio.Lock cache, volume/spread filters, and REST batch fetching (Task 26)
type: feedback
---

Key patterns from `agent/trading/pair_selector.py`:

1. **Double-checked locking**: Fast path outside lock (`if cache and not stale: return cache`), then re-check inside the lock after acquiring it. Prevents thundering herd without sacrificing performance on cache hits.

2. **Raise vs return for recoverable errors in `_refresh()`**: When the platform returns too few symbols, raise `RuntimeError` rather than returning a fallback `SelectedPairs`. The outer `get_active_pairs()` try/except then decides whether to use stale cache or `_fallback_result()`. If `_refresh()` returns normally, `_cache` is always overwritten — the stale-preservation path is only reachable via exceptions.

3. **Test default ticker entry must have narrow spread**: The default `_ticker_entry()` helper uses `high="102.0", low="98.5", close="100.0"` → spread = 3.5%, safely below the 5% filter. Using `high=105/low=95` (10% spread) causes all default entries to be filtered out and many tests to silently fail with fallback results.

4. **Small-symbol tests need `min_symbols_threshold=1`**: The `_MIN_SYMBOLS_THRESHOLD=5` guard triggers when tests use fewer than 5 symbols in the prices response. Pass `min_symbols_threshold=1` to the constructor in tests that need to work with 2-4 symbols.

5. **`asyncio.Lock` must be an instance attribute, not module-level**: Each `PairSelector` instance needs its own lock. Module-level locks would serialize across all instances.

6. **Fallback result on stale cache**: After `invalidate()` sets `_cache=None`, any subsequent refresh failure returns `_fallback_result()` (not stale data). To test stale-cache preservation on failure, manually set `selector._cache` to a stale `SelectedPairs` with `refreshed_at=time.monotonic() - 7200.0` instead of calling `invalidate()`.

**Why:** These patterns ensure cache correctness under concurrency, test isolation, and graceful degradation.

**How to apply:** Any time implementing a cached async resource that must refresh periodically with fallback behavior.
