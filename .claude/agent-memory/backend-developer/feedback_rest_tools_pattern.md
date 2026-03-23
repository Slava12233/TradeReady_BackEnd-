---
name: REST tools extension pattern
description: How to add new PlatformRESTClient methods and tool wrappers in agent/tools/rest_tools.py (Task 33)
type: feedback
---

When extending `PlatformRESTClient` with new HTTP verbs beyond GET/POST, call `self._client.<verb>(...)` directly inside the `log_api_call` context manager — do NOT add a `_put` or `_delete` helper. The existing `_get`/`_post` helpers are only used for simple fire-and-forget calls; structured methods with logging use `self._client.<verb>` directly.

**Why:** Consistency with how all existing structured methods (`create_backtest`, `start_backtest`, `compare_versions`, etc.) already bypass the helpers and call `self._client.post/get` directly for fine-grained logging control.

**How to apply:** For any new HTTP method (PUT, PATCH, DELETE): add `self._client.<method>(path, headers=self._trace_headers(), json=body)` inside `async with log_api_call(...) as ctx:`, then `ctx["response_status"] = response.status_code`, then `response.raise_for_status()`.

Tool function name convention: when the client method name is ambiguous (e.g. `analyze_decisions`), prefix with the domain at the tool layer (e.g. `analyze_agent_decisions`) to avoid name collisions with other tool sets.

The existing test for "returns N tools" must be updated when adding tools. Also update the `test_expected_tool_names_present` set.
