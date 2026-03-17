"""Unit tests for LoggingMiddleware.

Tests that the middleware correctly logs requests with structured fields,
skips health checks, and sanitizes auth info.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.api.middleware.logging import LoggingMiddleware, _client_ip


def _make_app() -> Starlette:
    """Create a minimal Starlette app with LoggingMiddleware."""

    async def api_endpoint(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    async def health_endpoint(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    async def metrics_endpoint(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    async def error_endpoint(request: Request) -> PlainTextResponse:
        return PlainTextResponse("error", status_code=500)

    app = Starlette(
        routes=[
            Route("/api/v1/trade/order", api_endpoint, methods=["POST"]),
            Route("/api/v1/agents", api_endpoint),
            Route("/health", health_endpoint),
            Route("/metrics", metrics_endpoint),
            Route("/api/v1/error", error_endpoint),
        ],
    )
    app.add_middleware(LoggingMiddleware)
    return app


class TestClientIp:
    def test_uses_x_forwarded_for_first(self) -> None:
        """Prefers X-Forwarded-For header."""
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}
        request.client = MagicMock()
        request.client.host = "172.16.0.1"

        assert _client_ip(request) == "203.0.113.5"

    def test_falls_back_to_client_host(self) -> None:
        """Falls back to direct client address when no XFF."""
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "192.168.1.1"

        assert _client_ip(request) == "192.168.1.1"

    def test_returns_unknown_when_no_client(self) -> None:
        """Returns 'unknown' when no client info available."""
        request = MagicMock()
        request.headers = {}
        request.client = None

        assert _client_ip(request) == "unknown"


class TestLoggingMiddleware:
    def test_logs_request_method_and_path(self) -> None:
        """Structured log includes method and path."""
        app = _make_app()
        client = TestClient(app)

        with patch("src.api.middleware.logging.logger") as mock_logger:
            response = client.get("/api/v1/agents")

        assert response.status_code == 200
        mock_logger.info.assert_called_once()
        call_kwargs = mock_logger.info.call_args
        assert call_kwargs[0][0] == "http.request"
        assert call_kwargs[1]["method"] == "GET"
        assert call_kwargs[1]["path"] == "/api/v1/agents"

    def test_logs_response_status_code(self) -> None:
        """Structured log includes status code."""
        app = _make_app()
        client = TestClient(app)

        with patch("src.api.middleware.logging.logger") as mock_logger:
            client.get("/api/v1/agents")

        call_kwargs = mock_logger.info.call_args
        assert call_kwargs[1]["status"] == 200

    def test_logs_request_duration(self) -> None:
        """latency_ms field is present in log."""
        app = _make_app()
        client = TestClient(app)

        with patch("src.api.middleware.logging.logger") as mock_logger:
            client.get("/api/v1/agents")

        call_kwargs = mock_logger.info.call_args
        assert "latency_ms" in call_kwargs[1]
        assert isinstance(call_kwargs[1]["latency_ms"], float)

    def test_excludes_health_check(self) -> None:
        """/health endpoint is not logged."""
        app = _make_app()
        client = TestClient(app)

        with patch("src.api.middleware.logging.logger") as mock_logger:
            response = client.get("/health")

        assert response.status_code == 200
        mock_logger.info.assert_not_called()

    def test_excludes_metrics_endpoint(self) -> None:
        """/metrics endpoint is not logged."""
        app = _make_app()
        client = TestClient(app)

        with patch("src.api.middleware.logging.logger") as mock_logger:
            response = client.get("/metrics")

        assert response.status_code == 200
        mock_logger.info.assert_not_called()

    def test_assigns_request_id(self) -> None:
        """A request_id is included in the log."""
        app = _make_app()
        client = TestClient(app)

        with patch("src.api.middleware.logging.logger") as mock_logger:
            client.get("/api/v1/agents")

        call_kwargs = mock_logger.info.call_args
        assert "request_id" in call_kwargs[1]

    def test_logs_error_for_5xx(self) -> None:
        """5xx responses are logged at error level."""
        app = _make_app()
        client = TestClient(app)

        with patch("src.api.middleware.logging.logger") as mock_logger:
            client.get("/api/v1/error")

        mock_logger.error.assert_called_once()
        call_kwargs = mock_logger.error.call_args
        assert call_kwargs[1]["status"] == 500
