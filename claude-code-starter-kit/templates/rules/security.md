---
paths:
  - "**/*"
---

# Security Rules

## Secrets Management

- **Never hardcode secrets** — all secrets via environment variables
- **Never log secrets** — API keys, passwords, tokens must never appear in logs
- **Never commit secrets** — `.env` files must be in `.gitignore`
- Use secure secret generation (e.g., `secrets.token_urlsafe()`, `crypto.randomBytes()`)

## Input Validation

- **Validate all user input** at system boundaries (API endpoints, form submissions)
- **Parameterize all queries** — never interpolate user input into SQL/NoSQL queries
- **Sanitize output** — escape user-generated content before rendering in HTML
- **Validate file paths** — prevent path traversal (`../`)
- **Validate URLs** — prevent SSRF (server-side request forgery)

## Authentication & Authorization

- Auth checks on every protected endpoint — never rely on client-side checks
- Use the project's auth middleware — don't roll custom auth
- Verify ownership/permissions for every resource access (prevent IDOR)
- Rate limit authentication endpoints

## Data Protection

- Hash passwords with bcrypt/argon2 — never store plaintext
- Encrypt sensitive data at rest
- Use HTTPS for all external communication
- Minimize data exposure in API responses — only return needed fields

## Dependencies

- Keep dependencies updated
- Review new dependencies for security before adding
- Prefer well-maintained packages with active security response

## Error Handling

- Never expose stack traces in production
- Never expose internal paths or database details in error messages
- Log security events (failed auth, permission denied) for monitoring
