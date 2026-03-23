---
name: sdk_tools_extension_pattern
description: How to add new tool functions to agent/tools/sdk_tools.py following the closure and serialization conventions
type: feedback
---

When adding new tools to `get_sdk_tools()`:

1. Verify the method exists on `AsyncAgentExchangeClient` in `sdk/agentexchange/async_client.py` before writing the wrapper.
2. Add a module-level `_serialize_*()` helper for any new response type that needs repeated serialization (e.g., `_serialize_order()` for `Order` dataclasses). Keep tool closures thin — they call the helper, not inline serialization.
3. All tool closures accept `ctx: Any` as first arg (Pydantic AI RunContext, injected automatically). Use `# noqa: ANN401` on the `Any` annotation.
4. Wrap every SDK call in `async with log_api_call("sdk", "<tool_name>", **kwargs) as log_ctx:` and set `log_ctx["response_status"] = 200` on success.
5. Catch only `AgentExchangeError` — never bare except. Return `{"error": str(exc)}` on failure and log a warning.
6. Add the new function to the `return [...]` list at the bottom of `get_sdk_tools()`.
7. Update the existing `test_returns_N_callables` and `test_tool_names` assertions in `test_sdk_tools.py` to reflect the new count and names.
8. Add a new test class per tool following the `_setup()` + class-per-subject pattern. Use `_make_pending_order()` (module-level helper) for pending order mocks.

**Why:** Enforces consistency with `log_api_call` instrumentation, structured error contract (`{"error": ...}`), and ensures the LLM can handle failures gracefully without workflow crashes.

**How to apply:** Any time a new SDK method needs to be exposed as an agent tool.
