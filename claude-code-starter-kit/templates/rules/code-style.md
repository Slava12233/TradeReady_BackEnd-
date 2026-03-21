---
paths:
  - "**/*"
---

# Code Style Rules

<!-- BOOTSTRAP: Customize these rules for your project's language and framework -->

## General

- Follow the project's established patterns — read nearby files before writing new code
- Keep functions focused — one function, one responsibility
- Prefer explicit over implicit — named parameters, clear variable names
- No magic numbers — use named constants

## Naming

- Files: `{{FILE_NAMING}}` (e.g., `snake_case.py`, `kebab-case.ts`, `PascalCase.go`)
- Classes/Types: `PascalCase`
- Functions/Methods: `{{FUNCTION_NAMING}}` (e.g., `snake_case`, `camelCase`)
- Constants: `UPPER_SNAKE_CASE`
- Private members: `{{PRIVATE_CONVENTION}}` (e.g., `_prefix`, `#private`)
- Boolean variables: prefix with `is`, `has`, `should`, `can`

## Import Order

1. Standard library / built-in modules
2. Third-party packages
3. Local/project imports

<!-- Enforced by linter: {{LINTER_NAME}} -->

## Error Handling

- Use the project's exception/error hierarchy — never bare `throw` or `raise`
- Always catch specific exceptions — never bare `catch` or `except`
- Log errors with context (what operation, what input)
- Fail closed on security-sensitive errors

## Documentation

- Public functions need docstrings/JSDoc with parameter descriptions
- Complex logic needs inline comments explaining WHY, not WHAT
- Don't comment obvious code

## Type Safety

- All public function signatures must have type annotations
- Avoid `any` / `object` / untyped — use specific types
- Use the project's type system fully (generics, unions, interfaces)
