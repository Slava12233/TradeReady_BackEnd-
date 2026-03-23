---
name: recovery_manager_patterns
description: Patterns from implementing RecoveryManager 3-state machine in agent/strategies/risk/recovery.py (Task 21)
type: feedback
---

Use a plain `@dataclass` (not frozen) for `RecoverySnapshot` to allow field access without the `object.__setattr__` workaround; reserve frozen dataclasses for config-like primitives (e.g. `RecoveryConfig`).

**Why:** `RecoverySnapshot` is a mutable point-in-time value object that gets replaced wholesale on every state transition. Freezing it would require `object.__setattr__` gymnastics when constructing updated copies inside methods, adding noise with no benefit.

**How to apply:** Use `frozen=True` only on config primitives that must never be mutated after construction. Use plain `@dataclass` for mutable snapshots.

---

When a Redis hash stores a state machine snapshot, decode `bytes` keys/values from `hgetall` explicitly in `load()`:
```python
str_data = {
    k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
    for k, v in data.items()
}
```

**Why:** `redis.asyncio` `hgetall` returns `dict[bytes, bytes]` by default. Without decoding, `from_dict` receives bytes where it expects strings and raises `ValueError` or `KeyError`.

**How to apply:** Always decode in the `load()` method before calling `from_dict`.

---

For state machines with an equity gate that blocks transition to the final state: apply the gate in two places — in `get_size_multiplier` (read-only check on every tick) AND in `advance_day` (write-path when actually advancing). This prevents the multiplier from ever persisting at 1.0 before the equity condition is met.

**Why:** If only applied in `advance_day`, a crashed process could reload a snapshot with `current_multiplier=1.0` but equity still below target and bypass the gate. Defence in depth.

**How to apply:** `_apply_equity_gate` in `get_size_multiplier` reads the snapshot's multiplier but caps it at 0.75 if equity is below target. `advance_day` writes the capped value when transitioning at day 4 without equity recovery.
