---
name: fastapi-backend-development
description: |
  Teaches the agent how to build async FastAPI services for the AiTradingAgent crypto trading platform.
  Use when: adding API routes, schemas, middleware; implementing auth; handling errors; configuring CORS/logging; or working with FastAPI + Pydantic v2 in this project.
---

# FastAPI Backend Development

## Stack

- Python 3.12+, FastAPI, Pydantic v2, pydantic-settings
- Async handlers, dependency injection, async middleware
- Auth: API key (X-API-Key header) + JWT (Bearer token)
- Rate limiting via Redis sliding window
- OpenAPI docs at `/docs`, health at `/health`, Prometheus at `/metrics`

## Project Layout

| Purpose | Path |
|---------|------|
| Routes | `src/api/routes/` |
| Schemas | `src/api/schemas/` |
| Middleware | `src/api/middleware/` |
| Config | `src/config.py` |

## Config

- Use `pydantic-settings` in `src/config.py` for env-based config.
- Load via `.env` or environment variables.

## Auth

- API key: `X-API-Key` header
- JWT: `Authorization: Bearer <token>`
- Use dependency injection for `current_account` from request context.
- Validate auth before any protected endpoint.

## Error Responses

Standard shape:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "details": {}
  }
}
```

## Error Codes

| Code | HTTP | Use |
|------|------|-----|
| INVALID_API_KEY | 401 | Invalid or missing API key |
| RATE_LIMIT_EXCEEDED | 429 | Too many requests |
| INSUFFICIENT_BALANCE | 400 | Not enough balance for order |
| INVALID_SYMBOL | 400 | Unknown or unsupported symbol |
| DAILY_LOSS_LIMIT | 403 | Daily loss limit hit |
| ORDER_NOT_FOUND | 404 | Order ID not found |
| INTERNAL_ERROR | 500 | Unexpected server error |

## Handlers

- All handlers must be `async`.
- Use dependency injection for DB sessions, Redis, current account.
- Use Pydantic v2 schemas for request/response.

## Middleware

- CORS middleware enabled
- Request/response logging middleware
- Rate limiting via Redis sliding window
- Auth middleware for protected routes

## Conventions

- Use `Depends()` for DB session, Redis, auth.
- Keep schemas in `src/api/schemas/`, routes in `src/api/routes/`.
- Use `raise HTTPException` with appropriate status and structured error body.
- Ensure `/health` returns service status; `/metrics` exposes Prometheus metrics.

## References

- For the complete REST API specification, see [references/api-spec.md](references/api-spec.md)
