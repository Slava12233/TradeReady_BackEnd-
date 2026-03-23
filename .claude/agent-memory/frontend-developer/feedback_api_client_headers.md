---
name: api_client_header_priority
description: Explicit headers passed in options.headers to api-client request() were silently overwritten by the X-Agent-Id auto-inject in executeRequest
type: feedback
---

When calling `request()` with custom `headers: { "X-Agent-Id": someOtherAgentId }`, the auto-inject block in `executeRequest` was spreading options.headers first then unconditionally setting `headers["X-Agent-Id"] = activeAgentId` from localStorage — overwriting the explicit value.

**Why:** The original code structured header merging with the auto-inject happening after the spread, so caller-supplied values were silently ignored.

**How to apply:** The fix (applied in Task 35) restructures `executeRequest` to: (1) check if `explicitHeaders["X-Agent-Id"]` is already set, and skip auto-inject if so; (2) `Object.assign(headers, explicitHeaders)` at the end so explicit headers always win. When writing API client functions that need to override agent context (e.g., multi-agent comparison charts), pass `headers: { "X-Agent-Id": agentId }` — it will now work correctly.
