"""Authentication utilities for the AI Agent Crypto Trading Platform.

Responsibilities
----------------
1. API key and secret generation — ``ak_live_`` / ``sk_live_`` prefixed tokens
   produced with :func:`secrets.token_urlsafe`.
2. Bcrypt hashing — wrap the synchronous ``bcrypt`` library so callers never
   touch plaintext secrets after initial generation.
3. JWT creation and verification — HS256 tokens carrying ``account_id`` and
   issued/expiry timestamps, signed with the ``jwt_secret`` from
   :class:`~src.config.Settings`.

All cryptographic operations are CPU-bound; the helpers that wrap them are
synchronous by design and must be called from a thread pool when used inside
an async FastAPI handler (``asyncio.get_event_loop().run_in_executor``).

Example::

    from src.accounts.auth import generate_api_credentials, create_jwt, verify_jwt

    creds = generate_api_credentials()
    print(creds.api_key)     # ak_live_<64 url-safe chars>
    print(creds.api_secret)  # sk_live_<64 url-safe chars>

    token = create_jwt(account_id=some_uuid, jwt_secret="...", expiry_hours=1)
    payload = verify_jwt(token, jwt_secret="...")
    print(payload.account_id)
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import jwt
from jwt import DecodeError, ExpiredSignatureError, InvalidTokenError as _JWTInvalidTokenError

from src.utils.exceptions import AuthenticationError, InvalidTokenError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_KEY_PREFIX = "ak_live_"
_API_SECRET_PREFIX = "sk_live_"
_TOKEN_BYTES = 48  # secrets.token_urlsafe(48) → 64 url-safe chars
_BCRYPT_ROUNDS = 12
_JWT_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ApiCredentials:
    """Raw (plaintext) API key and secret returned once on account creation.

    Both values are shown to the user exactly once.  Only hashes are persisted
    in the database.

    Attributes:
        api_key:    Plaintext API key with ``ak_live_`` prefix.  Stored in the
                    ``accounts.api_key`` column (plaintext) for O(1) lookup.
        api_secret: Plaintext API secret with ``sk_live_`` prefix.  **Never**
                    stored; only its bcrypt hash is kept.
        api_key_hash:    Bcrypt hash of ``api_key`` for double-verification.
        api_secret_hash: Bcrypt hash of ``api_secret`` for HMAC signing checks.
    """

    api_key: str
    api_secret: str
    api_key_hash: str
    api_secret_hash: str


@dataclass(frozen=True, slots=True)
class JwtPayload:
    """Decoded and verified JWT payload.

    Attributes:
        account_id: The account UUID embedded in the token.
        issued_at:  UTC datetime when the token was issued.
        expires_at: UTC datetime when the token expires.
    """

    account_id: UUID
    issued_at: datetime
    expires_at: datetime


# ---------------------------------------------------------------------------
# API key generation
# ---------------------------------------------------------------------------


def generate_api_credentials() -> ApiCredentials:
    """Generate a fresh API key/secret pair with bcrypt hashes.

    Uses :func:`secrets.token_urlsafe` with ``TOKEN_BYTES=48`` which produces
    64 URL-safe characters.  Both the key and the secret are hashed with bcrypt
    at ``BCRYPT_ROUNDS=12`` rounds before being returned.

    Returns:
        :class:`ApiCredentials` containing plaintext key/secret and their
        bcrypt hashes ready for database insertion.

    Example::

        creds = generate_api_credentials()
        # Persist to DB:
        #   accounts.api_key        = creds.api_key          (plaintext — for lookup)
        #   accounts.api_key_hash   = creds.api_key_hash     (bcrypt hash)
        #   accounts.api_secret_hash = creds.api_secret_hash  (bcrypt hash)
    """
    api_key = _API_KEY_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)
    api_secret = _API_SECRET_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)

    api_key_hash = _bcrypt_hash(api_key)
    api_secret_hash = _bcrypt_hash(api_secret)

    return ApiCredentials(
        api_key=api_key,
        api_secret=api_secret,
        api_key_hash=api_key_hash,
        api_secret_hash=api_secret_hash,
    )


# ---------------------------------------------------------------------------
# Bcrypt helpers
# ---------------------------------------------------------------------------


def _bcrypt_hash(plaintext: str) -> str:
    """Return a bcrypt hash string for *plaintext*.

    Args:
        plaintext: The value to hash (API key, secret, or password).

    Returns:
        A bcrypt hash string (60 characters, ``$2b$`` prefix).
    """
    hashed: bytes = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return hashed.decode()


def verify_api_key(plaintext: str, stored_hash: str) -> bool:
    """Verify a plaintext API key against its stored bcrypt hash.

    Args:
        plaintext:   The raw API key presented by the client.
        stored_hash: The bcrypt hash stored in the ``accounts`` table.

    Returns:
        ``True`` if the key matches, ``False`` otherwise.

    Example::

        if not verify_api_key(header_key, account.api_key_hash):
            raise AuthenticationError("Invalid API key.")
    """
    try:
        return bcrypt.checkpw(plaintext.encode(), stored_hash.encode())
    except ValueError:
        return False


def verify_api_secret(plaintext: str, stored_hash: str) -> bool:
    """Verify a plaintext API secret against its stored bcrypt hash.

    Used for HMAC-signed order requests where the client proves possession of
    the secret without transmitting it in plaintext.

    Args:
        plaintext:   The raw API secret to verify.
        stored_hash: The bcrypt hash stored in the ``accounts`` table.

    Returns:
        ``True`` if the secret matches, ``False`` otherwise.
    """
    try:
        return bcrypt.checkpw(plaintext.encode(), stored_hash.encode())
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def create_jwt(
    account_id: UUID,
    jwt_secret: str,
    expiry_hours: int = 1,
) -> str:
    """Create a signed HS256 JWT token for an account.

    The token payload contains:
    - ``sub``  — string representation of ``account_id``
    - ``iat``  — issued-at Unix timestamp
    - ``exp``  — expiry Unix timestamp (``iat + expiry_hours * 3600``)

    Args:
        account_id:   The account's UUID to embed as the subject claim.
        jwt_secret:   The HS256 signing secret (``Settings.jwt_secret``).
        expiry_hours: Token lifetime in hours (default: 1).

    Returns:
        A signed JWT string ready to be included in an ``Authorization: Bearer``
        header.

    Example::

        token = create_jwt(account_id=account.id, jwt_secret=settings.jwt_secret)
        # → "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    """
    now = datetime.now(tz=timezone.utc)
    expires_at = now + timedelta(hours=expiry_hours)

    payload: dict[str, object] = {
        "sub": str(account_id),
        "iat": now,
        "exp": expires_at,
    }

    token: str = jwt.encode(payload, jwt_secret, algorithm=_JWT_ALGORITHM)
    return token


def verify_jwt(token: str, jwt_secret: str) -> JwtPayload:
    """Decode and verify a JWT token, returning a typed payload.

    Validation steps performed by PyJWT:
    - Signature integrity (HS256 + ``jwt_secret``)
    - Expiry (``exp`` claim must be in the future)
    - Issued-at (``iat`` claim must be present)

    Args:
        token:      The raw JWT string from the ``Authorization`` header.
        jwt_secret: The HS256 signing secret (``Settings.jwt_secret``).

    Returns:
        :class:`JwtPayload` with ``account_id``, ``issued_at``, and
        ``expires_at`` populated.

    Raises:
        :exc:`~src.utils.exceptions.InvalidTokenError`: If the token is
            expired, has an invalid signature, is malformed, or is missing
            required claims.

    Example::

        try:
            payload = verify_jwt(bearer_token, settings.jwt_secret)
        except InvalidTokenError as exc:
            return JSONResponse(exc.to_dict(), status_code=exc.http_status)
    """
    try:
        decoded: dict[str, object] = jwt.decode(
            token,
            jwt_secret,
            algorithms=[_JWT_ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
    except ExpiredSignatureError:
        raise InvalidTokenError("JWT token has expired.")
    except (DecodeError, _JWTInvalidTokenError) as exc:
        raise InvalidTokenError(f"JWT token is invalid: {exc}") from exc

    try:
        account_id = UUID(str(decoded["sub"]))
    except (ValueError, KeyError) as exc:
        raise InvalidTokenError("JWT token contains an invalid 'sub' claim.") from exc

    # PyJWT guarantees iat and exp are present numeric values when decode()
    # succeeds with options={"require": ["iat", "exp"]}.
    issued_at = datetime.fromtimestamp(float(decoded["iat"]), tz=timezone.utc)  # type: ignore[arg-type]
    expires_at = datetime.fromtimestamp(float(decoded["exp"]), tz=timezone.utc)  # type: ignore[arg-type]

    return JwtPayload(
        account_id=account_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# Convenience: authenticate a raw API key header value
# ---------------------------------------------------------------------------


def authenticate_api_key(raw_key: str, stored_hash: str) -> None:
    """Verify a raw API key and raise if it does not match.

    Thin wrapper around :func:`verify_api_key` that converts a ``False`` result
    into the platform's typed :exc:`~src.utils.exceptions.AuthenticationError`.

    Args:
        raw_key:     The API key value from the ``X-API-Key`` header.
        stored_hash: The bcrypt hash from the database row.

    Raises:
        :exc:`~src.utils.exceptions.AuthenticationError`: If the key is
            invalid or does not match the stored hash.

    Example::

        authenticate_api_key(request.headers["X-API-Key"], account.api_key_hash)
        # No exception → key is valid
    """
    if not raw_key.startswith(_API_KEY_PREFIX) or len(raw_key) != len(_API_KEY_PREFIX) + 64:
        raise AuthenticationError("API key format is invalid.")
    if not verify_api_key(raw_key, stored_hash):
        raise AuthenticationError("API key is invalid.")


__all__ = [
    "ApiCredentials",
    "JwtPayload",
    "generate_api_credentials",
    "verify_api_key",
    "verify_api_secret",
    "create_jwt",
    "verify_jwt",
    "authenticate_api_key",
]
