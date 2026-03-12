"""Unit tests for src/accounts/auth.py — API credentials, bcrypt, JWT."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.accounts.auth import (
    authenticate_api_key,
    create_jwt,
    generate_api_credentials,
    hash_password,
    verify_api_secret,
    verify_jwt,
    verify_password,
)
from src.utils.exceptions import AuthenticationError, InvalidTokenError

_JWT_SECRET = "test_secret_that_is_at_least_32_characters_long"


# ---------------------------------------------------------------------------
# API credential generation
# ---------------------------------------------------------------------------


class TestGenerateApiCredentials:
    def test_returns_correct_prefixes(self):
        creds = generate_api_credentials()
        assert creds.api_key.startswith("ak_live_")
        assert creds.api_secret.startswith("sk_live_")

    def test_key_length(self):
        creds = generate_api_credentials()
        # ak_live_ (8 chars) + 64 url-safe chars = 72
        assert len(creds.api_key) == 72
        assert len(creds.api_secret) == 72

    def test_unique_per_call(self):
        c1 = generate_api_credentials()
        c2 = generate_api_credentials()
        assert c1.api_key != c2.api_key
        assert c1.api_secret != c2.api_secret

    def test_hashes_are_bcrypt(self):
        creds = generate_api_credentials()
        assert creds.api_key_hash.startswith("$2b$")
        assert creds.api_secret_hash.startswith("$2b$")


# ---------------------------------------------------------------------------
# Password hashing / verification
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    def test_hash_returns_bcrypt(self):
        h = hash_password("mypassword")
        assert h.startswith("$2b$")

    def test_verify_correct(self):
        h = hash_password("mypassword")
        assert verify_password("mypassword", h) is True

    def test_verify_incorrect(self):
        h = hash_password("mypassword")
        assert verify_password("wrong", h) is False


# ---------------------------------------------------------------------------
# API secret verification
# ---------------------------------------------------------------------------


class TestVerifyApiSecret:
    def test_correct(self):
        creds = generate_api_credentials()
        assert verify_api_secret(creds.api_secret, creds.api_secret_hash) is True

    def test_incorrect(self):
        creds = generate_api_credentials()
        assert verify_api_secret("sk_live_wrong", creds.api_secret_hash) is False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


class TestCreateJwt:
    def test_valid_structure(self):
        aid = uuid4()
        token = create_jwt(aid, _JWT_SECRET, expiry_hours=1)
        payload = verify_jwt(token, _JWT_SECRET)
        assert payload.account_id == aid
        assert payload.issued_at is not None
        assert payload.expires_at is not None

    def test_expiry_hours(self):
        aid = uuid4()
        token = create_jwt(aid, _JWT_SECRET, expiry_hours=5)
        payload = verify_jwt(token, _JWT_SECRET)
        delta = payload.expires_at - payload.issued_at
        assert abs(delta.total_seconds() - 5 * 3600) < 2


class TestVerifyJwt:
    def test_valid_token(self):
        aid = uuid4()
        token = create_jwt(aid, _JWT_SECRET)
        payload = verify_jwt(token, _JWT_SECRET)
        assert payload.account_id == aid

    def test_expired_token(self):
        import jwt as pyjwt

        aid = uuid4()
        now = datetime.now(tz=UTC) - timedelta(hours=2)
        raw = {
            "sub": str(aid),
            "iat": now,
            "exp": now + timedelta(hours=1),  # already expired
        }
        token = pyjwt.encode(raw, _JWT_SECRET, algorithm="HS256")
        with pytest.raises(InvalidTokenError, match="expired"):
            verify_jwt(token, _JWT_SECRET)

    def test_invalid_signature(self):
        aid = uuid4()
        token = create_jwt(aid, _JWT_SECRET)
        with pytest.raises(InvalidTokenError):
            verify_jwt(token, "wrong_secret_that_is_at_least_32_chars")

    def test_malformed_token(self):
        with pytest.raises(InvalidTokenError):
            verify_jwt("not.a.jwt", _JWT_SECRET)

    def test_missing_sub_claim(self):
        import jwt as pyjwt

        now = datetime.now(tz=UTC)
        raw = {"iat": now, "exp": now + timedelta(hours=1)}
        token = pyjwt.encode(raw, _JWT_SECRET, algorithm="HS256")
        with pytest.raises(InvalidTokenError):
            verify_jwt(token, _JWT_SECRET)


# ---------------------------------------------------------------------------
# authenticate_api_key
# ---------------------------------------------------------------------------


class TestAuthenticateApiKey:
    def test_valid(self):
        creds = generate_api_credentials()
        # Should not raise
        authenticate_api_key(creds.api_key, creds.api_key_hash)

    def test_bad_hash(self):
        creds = generate_api_credentials()
        other = generate_api_credentials()
        with pytest.raises(AuthenticationError):
            authenticate_api_key(creds.api_key, other.api_key_hash)

    def test_bad_format(self):
        with pytest.raises(AuthenticationError, match="format"):
            authenticate_api_key("bad_key", "$2b$12$fake")
