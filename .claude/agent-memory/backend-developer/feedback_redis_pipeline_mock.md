---
name: feedback_redis_pipeline_mock
description: How to correctly mock Redis pipelines in async pytest — pipeline() must use MagicMock, not AsyncMock
type: feedback
---

`redis.pipeline()` is a synchronous call. If you mock it as `AsyncMock`, pytest returns a coroutine object instead of the pipeline, and the pipeline's `.lpush` / `.ltrim` / `.expire` methods are never reached.

**Rule:** Always mock `redis.pipeline` with `MagicMock(return_value=pipe)` where `pipe` is a plain `MagicMock`. Only `pipe.execute` should be `AsyncMock` (because it is awaited).

```python
pipe = MagicMock()
pipe.lpush = MagicMock(return_value=pipe)
pipe.ltrim = MagicMock(return_value=pipe)
pipe.expire = MagicMock(return_value=pipe)
pipe.execute = AsyncMock(return_value=[1, True, True])
redis.pipeline = MagicMock(return_value=pipe)  # NOT AsyncMock
```

**Why:** `redis.asyncio.Redis.pipeline()` returns a `Pipeline` object synchronously. The `await` comes only when you call `await pipe.execute()`. Using `AsyncMock` for `pipeline()` wraps it in a coroutine that can never be `.lpush()`-ed.

**How to apply:** Whenever writing tests for code that uses `redis.pipeline()`, use this exact pattern.
