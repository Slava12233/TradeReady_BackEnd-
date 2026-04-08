"""Integration tests for metrics REST endpoints.

Covers:

- ``POST /api/v1/metrics/deflated-sharpe``

The endpoint requires authentication.  All tests use the sync ``TestClient``
with the full middleware stack and mocked infrastructure (no real DB or Redis
needed).  The auth middleware is patched via ``_authenticate_request`` so
that tests do not need a real account in the database.

Run with::

    pytest tests/integration/test_metrics_api.py -v
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from src.config import Settings

pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Test settings — safe fake values, no real infra
# ---------------------------------------------------------------------------

_TEST_JWT_SECRET = "test_secret_that_is_at_least_32_characters_long_for_hs256"

_TEST_SETTINGS = Settings(
    jwt_secret=_TEST_JWT_SECRET,
    database_url="postgresql+asyncpg://test:test@localhost:5432/test",
    redis_url="redis://localhost:6379/15",
    jwt_expiry_hours=1,
)

# ---------------------------------------------------------------------------
# Reusable return series fixtures
# ---------------------------------------------------------------------------

#: Minimal valid return series (exactly 10 observations).
_MIN_RETURNS = [0.001, -0.002, 0.003, 0.001, -0.001, 0.002, 0.0, -0.003, 0.004, 0.001]

#: 50-observation return series with a positive mean signal.
_SIGNAL_RETURNS = [0.001 + (-1) ** i * 0.005 for i in range(50)]

#: 100-observation return series used for significance tests.
_LARGE_RETURNS = [0.002 + (-1) ** i * 0.003 for i in range(100)]


# ---------------------------------------------------------------------------
# App / client factory
# ---------------------------------------------------------------------------


def _build_client(*, authenticated: bool = True) -> tuple[TestClient, object]:
    """Create a ``TestClient`` with mocked infrastructure.

    The metrics endpoint now requires authentication.  When ``authenticated``
    is ``True`` (default), ``_authenticate_request`` is patched to return a
    mock ``Account`` so that all requests are accepted by the auth middleware.
    When ``False``, ``_authenticate_request`` returns ``(None, None)`` so the
    middleware issues a 401 response — used to test that the endpoint is no
    longer public.

    Args:
        authenticated: Whether to inject a mock authenticated account.

    Returns:
        A tuple of ``(client, cleanup_fn)``.
    """
    from src.dependencies import get_db_session, get_redis, get_settings

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.ttl = AsyncMock(return_value=60)
    mock_redis.hget = AsyncMock(return_value=None)
    mock_redis.hset = AsyncMock(return_value=1)

    # Pipeline mock — required by RateLimitMiddleware
    mock_pipe = AsyncMock()
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    mock_pipe.incr = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 60])
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    # Build a minimal mock Account for the auth middleware.
    mock_account = MagicMock()
    mock_account.id = uuid4()
    mock_account.status = "active"

    # _authenticate_request is called at request time, not app-creation time,
    # so we use patch.start() to keep the patch alive across requests.
    if authenticated:
        auth_patcher = patch(
            "src.api.middleware.auth._authenticate_request",
            new_callable=AsyncMock,
            return_value=(mock_account, None),
        )
    else:
        auth_patcher = patch(
            "src.api.middleware.auth._authenticate_request",
            new_callable=AsyncMock,
            return_value=(None, None),
        )
    auth_patcher.start()

    with (
        patch("src.database.session.init_db", new_callable=AsyncMock),
        patch("src.database.session.close_db", new_callable=AsyncMock),
        patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=mock_redis),
        patch("src.api.websocket.handlers.start_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.handlers.stop_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.manager.ConnectionManager.disconnect_all", new_callable=AsyncMock),
    ):
        from src.main import create_app

        app = create_app()

        app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS

        async def _override_db():
            yield mock_session

        app.dependency_overrides[get_db_session] = _override_db

        async def _override_redis():
            yield mock_redis

        app.dependency_overrides[get_redis] = _override_redis

        client = TestClient(app, raise_server_exceptions=False)

    def _cleanup():
        app.dependency_overrides.clear()
        auth_patcher.stop()

    return client, _cleanup


# ---------------------------------------------------------------------------
# Tests: response schema
# ---------------------------------------------------------------------------


class TestDeflatedSharpeResponseSchema:
    """Tests for the response shape of POST /api/v1/metrics/deflated-sharpe."""

    def setup_method(self):
        self.client, self._cleanup = _build_client()

    def teardown_method(self):
        self._cleanup()

    def test_status_200_on_valid_request(self):
        """Valid request must return HTTP 200."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 1},
        )
        assert response.status_code == 200

    def test_response_contains_all_required_fields(self):
        """Response body must contain every documented field."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 1},
        )
        assert response.status_code == 200
        body = response.json()
        expected_fields = {
            "observed_sharpe",
            "expected_max_sharpe",
            "deflated_sharpe",
            "p_value",
            "is_significant",
            "num_trials",
            "num_returns",
            "skewness",
            "kurtosis",
        }
        assert expected_fields.issubset(body.keys()), (
            f"Missing fields: {expected_fields - body.keys()}"
        )

    def test_response_num_returns_matches_input_length(self):
        """num_returns in response must equal the number of returns supplied."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _SIGNAL_RETURNS, "num_trials": 5},
        )
        assert response.status_code == 200
        assert response.json()["num_returns"] == len(_SIGNAL_RETURNS)

    def test_response_num_trials_matches_input(self):
        """num_trials in response must mirror the request value."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 42},
        )
        assert response.status_code == 200
        assert response.json()["num_trials"] == 42

    def test_response_p_value_is_in_range(self):
        """p_value must be in [0, 1]."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _SIGNAL_RETURNS, "num_trials": 10},
        )
        assert response.status_code == 200
        p_value = response.json()["p_value"]
        assert 0.0 <= p_value <= 1.0

    def test_response_is_significant_is_bool(self):
        """is_significant must be a boolean."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 1},
        )
        assert response.status_code == 200
        assert isinstance(response.json()["is_significant"], bool)

    def test_response_numeric_fields_are_finite(self):
        """All numeric float fields must be finite (no NaN or Infinity)."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _SIGNAL_RETURNS, "num_trials": 10},
        )
        assert response.status_code == 200
        body = response.json()
        for field in ("observed_sharpe", "expected_max_sharpe", "deflated_sharpe", "p_value", "skewness", "kurtosis"):
            assert math.isfinite(body[field]), f"Field {field!r} is not finite: {body[field]}"

    def test_default_annualization_factor_is_252(self):
        """When annualization_factor is omitted it defaults to 252."""
        # Post without annualization_factor and with it set to 252 — results must match.
        payload = {"returns": _MIN_RETURNS, "num_trials": 1}
        resp_default = self.client.post("/api/v1/metrics/deflated-sharpe", json=payload)
        resp_explicit = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={**payload, "annualization_factor": 252},
        )
        assert resp_default.status_code == 200
        assert resp_explicit.status_code == 200
        assert resp_default.json()["observed_sharpe"] == resp_explicit.json()["observed_sharpe"]

    def test_custom_annualization_factor(self):
        """Supplying annualization_factor=52 (weekly) must produce a different SR."""
        payload_daily = {"returns": _MIN_RETURNS, "num_trials": 1, "annualization_factor": 252}
        payload_weekly = {"returns": _MIN_RETURNS, "num_trials": 1, "annualization_factor": 52}
        resp_daily = self.client.post("/api/v1/metrics/deflated-sharpe", json=payload_daily)
        resp_weekly = self.client.post("/api/v1/metrics/deflated-sharpe", json=payload_weekly)
        assert resp_daily.status_code == 200
        assert resp_weekly.status_code == 200
        assert resp_daily.json()["observed_sharpe"] != resp_weekly.json()["observed_sharpe"]


# ---------------------------------------------------------------------------
# Tests: is_significant returned correctly
# ---------------------------------------------------------------------------


class TestIsSignificantEndpoint:
    """Tests that the is_significant flag is computed and returned correctly."""

    def setup_method(self):
        self.client, self._cleanup = _build_client()

    def teardown_method(self):
        self._cleanup()

    def test_is_significant_consistent_with_p_value(self):
        """is_significant must be True iff p_value > 0.95."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _LARGE_RETURNS, "num_trials": 1},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["is_significant"] == (body["p_value"] > 0.95)

    def test_is_significant_false_with_many_trials(self):
        """Many trials make significance very hard — weak signal should fail."""
        # Alternating ±0.005 returns have zero mean → SR=0 → definitely not significant
        weak_returns = [0.005 * ((-1) ** i) for i in range(50)]
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": weak_returns, "num_trials": 1000},
        )
        assert response.status_code == 200
        assert response.json()["is_significant"] is False

    def test_is_significant_false_for_negative_sr(self):
        """Negative observed Sharpe must always produce is_significant=False."""
        negative_returns = [-0.001] * 50
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": negative_returns, "num_trials": 1},
        )
        assert response.status_code == 200
        assert response.json()["is_significant"] is False


# ---------------------------------------------------------------------------
# Tests: input validation (min returns length)
# ---------------------------------------------------------------------------


class TestMinReturnsValidation:
    """Tests for the minimum returns length constraint (>= 10)."""

    def setup_method(self):
        self.client, self._cleanup = _build_client()

    def teardown_method(self):
        self._cleanup()

    def test_empty_returns_returns_422(self):
        """Empty returns list must return HTTP 422 (Pydantic min_length validation)."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": [], "num_trials": 1},
        )
        assert response.status_code == 422

    def test_one_return_returns_422(self):
        """A single return value must return HTTP 422."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": [0.001], "num_trials": 1},
        )
        assert response.status_code == 422

    def test_nine_returns_returns_422(self):
        """Nine returns (one below min) must return HTTP 422."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": [0.001] * 9, "num_trials": 1},
        )
        assert response.status_code == 422

    def test_ten_returns_succeeds(self):
        """Exactly 10 returns (the minimum) must return HTTP 200."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 1},
        )
        assert response.status_code == 200

    def test_eleven_returns_succeeds(self):
        """11 returns (one above minimum) must succeed."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": [0.001] * 11, "num_trials": 1},
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tests: input validation (num_trials >= 1)
# ---------------------------------------------------------------------------


class TestNumTrialsValidation:
    """Tests for the num_trials >= 1 constraint."""

    def setup_method(self):
        self.client, self._cleanup = _build_client()

    def teardown_method(self):
        self._cleanup()

    def test_num_trials_zero_returns_422(self):
        """num_trials=0 must return HTTP 422 (Pydantic ge=1 validation)."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 0},
        )
        assert response.status_code == 422

    def test_num_trials_negative_returns_422(self):
        """Negative num_trials must return HTTP 422."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": -10},
        )
        assert response.status_code == 422

    def test_num_trials_one_is_valid(self):
        """num_trials=1 (the minimum) must return HTTP 200."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 1},
        )
        assert response.status_code == 200

    def test_num_trials_large_value_is_valid(self):
        """Large num_trials (e.g. 10000) must return HTTP 200."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 10000},
        )
        assert response.status_code == 200

    def test_num_trials_missing_returns_422(self):
        """Omitting num_trials entirely must return HTTP 422 (required field)."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS},
        )
        assert response.status_code == 422

    def test_returns_missing_returns_422(self):
        """Omitting returns entirely must return HTTP 422 (required field)."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"num_trials": 1},
        )
        assert response.status_code == 422

    def test_annualization_factor_zero_returns_422(self):
        """annualization_factor=0 must return HTTP 422 (ge=1 constraint)."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 1, "annualization_factor": 0},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: error response format
# ---------------------------------------------------------------------------


class TestErrorResponseFormat:
    """Tests that validation errors use the project's standard error envelope."""

    def setup_method(self):
        self.client, self._cleanup = _build_client()

    def teardown_method(self):
        self._cleanup()

    def test_missing_field_error_has_detail(self):
        """Pydantic validation errors on missing fields must include detail info."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"num_trials": 1},  # missing 'returns'
        )
        assert response.status_code == 422
        # FastAPI/Pydantic validation errors produce {"detail": [...]} by default
        body = response.json()
        assert "detail" in body

    def test_content_type_is_json(self):
        """Successful response must have Content-Type: application/json."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 1},
        )
        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]

    def test_non_json_body_returns_422(self):
        """Sending a non-JSON body must return HTTP 422."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: endpoint requires authentication
# ---------------------------------------------------------------------------


class TestAuthRequired:
    """Tests that the metrics endpoint requires authentication (no longer public)."""

    def setup_method(self):
        # Build a client that simulates unauthenticated requests so we can
        # verify the middleware returns 401.
        self.client, self._cleanup = _build_client(authenticated=False)

    def teardown_method(self):
        self._cleanup()

    def test_no_credentials_returns_401(self):
        """The endpoint must return 401 when no credentials are supplied."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 1},
        )
        assert response.status_code == 401

    def test_authenticated_request_succeeds(self):
        """An authenticated request must return 200."""
        # Build a second client that IS authenticated.
        authed_client, cleanup = _build_client(authenticated=True)
        try:
            response = authed_client.post(
                "/api/v1/metrics/deflated-sharpe",
                json={"returns": _MIN_RETURNS, "num_trials": 1},
            )
            assert response.status_code == 200
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# Tests: new upper-bound validations
# ---------------------------------------------------------------------------


class TestUpperBoundValidation:
    """Tests for the new upper-bound constraints on DeflatedSharpeRequest."""

    def setup_method(self):
        self.client, self._cleanup = _build_client()

    def teardown_method(self):
        self._cleanup()

    def test_returns_exceeding_max_length_returns_422(self):
        """returns list with more than 10,000 entries must return HTTP 422."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": [0.001] * 10_001, "num_trials": 1},
        )
        assert response.status_code == 422

    def test_returns_at_max_length_succeeds(self):
        """returns list with exactly 10,000 entries must return HTTP 200."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": [0.001] * 10_000, "num_trials": 1},
        )
        assert response.status_code == 200

    def test_num_trials_exceeding_upper_bound_returns_422(self):
        """num_trials above 100,000 must return HTTP 422."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 100_001},
        )
        assert response.status_code == 422

    def test_num_trials_at_upper_bound_succeeds(self):
        """num_trials equal to 100,000 must return HTTP 200."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 100_000},
        )
        assert response.status_code == 200

    def test_annualization_factor_exceeding_upper_bound_returns_422(self):
        """annualization_factor above 525,600 must return HTTP 422."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 1, "annualization_factor": 525_601},
        )
        assert response.status_code == 422

    def test_annualization_factor_at_upper_bound_succeeds(self):
        """annualization_factor equal to 525,600 must return HTTP 200."""
        response = self.client.post(
            "/api/v1/metrics/deflated-sharpe",
            json={"returns": _MIN_RETURNS, "num_trials": 1, "annualization_factor": 525_600},
        )
        assert response.status_code == 200
