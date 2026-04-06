---
paths:
  - "src/**/*.py"
  - "agent/**/*.py"
  - "tests/**/*.py"
  - "sdk/**/*.py"
---

# Backend Code Standards

- **Python 3.12+**, fully typed, `async/await` for all I/O
- **Pydantic v2** for all data models; **`Decimal`** (never `float`) for money/prices
- **Google-style docstrings** on every public class and function
- Custom exceptions from `src/utils/exceptions.py`; never bare `except:`
- All external calls (Redis, DB, WS) wrapped in try/except with logging; fail closed
- Import order: stdlib → third-party → local (ruff isort, `known-first-party = ["src", "sdk"]`)

## Security

- API keys: `secrets.token_urlsafe(48)` with `ak_live_` / `sk_live_` prefixes
- Store password/secret hashes (bcrypt), never plaintext
- Parameterized queries only (SQLAlchemy) — never raw f-strings in SQL
- All secrets via environment variables

## Naming

- Files: `snake_case.py`, Classes: `PascalCase`, Functions: `snake_case`
- Constants: `UPPER_SNAKE_CASE`, Private: `_prefix`

## API Design

- All routes under `/api/v1/` prefix
- Error format: `{"error": {"code": "...", "message": "..."}}`
- Rate limit headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
