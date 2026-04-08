"""Unit tests for SSRF protection on webhook URLs.

Tests cover :func:`src.webhooks.dispatcher.validate_webhook_url` directly,
plus the schema-level validators on :class:`WebhookCreateRequest` and
:class:`WebhookUpdateRequest`, and the defence-in-depth path inside
:func:`src.tasks.webhook_tasks._async_dispatch`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.webhooks.dispatcher import validate_webhook_url

# ---------------------------------------------------------------------------
# validate_webhook_url — scheme checks
# ---------------------------------------------------------------------------


class TestSchemeValidation:
    """validate_webhook_url must only accept https:// URLs."""

    def test_https_passes(self):
        """A valid https URL is returned unchanged."""
        url = "https://example.com/hooks"
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
            result = validate_webhook_url(url)
        assert result == url

    def test_http_rejected(self):
        """http:// scheme raises ValueError."""
        with pytest.raises(ValueError, match="must use the https scheme"):
            validate_webhook_url("http://example.com/hooks")

    def test_ftp_rejected(self):
        """ftp:// scheme raises ValueError."""
        with pytest.raises(ValueError, match="must use the https scheme"):
            validate_webhook_url("ftp://example.com/hooks")

    def test_empty_scheme_rejected(self):
        """A URL with no scheme raises ValueError."""
        with pytest.raises(ValueError, match="must use the https scheme"):
            validate_webhook_url("//example.com/hooks")

    def test_file_scheme_rejected(self):
        """file:// scheme raises ValueError."""
        with pytest.raises(ValueError, match="must use the https scheme"):
            validate_webhook_url("file:///etc/passwd")


# ---------------------------------------------------------------------------
# validate_webhook_url — bare IP address checks
# ---------------------------------------------------------------------------


class TestBareIpRejection:
    """Bare IP literals must be rejected regardless of the address range."""

    def test_bare_ipv4_loopback_rejected(self):
        """https://127.0.0.1/... is rejected as a bare IP."""
        with pytest.raises(ValueError, match="bare IP address"):
            validate_webhook_url("https://127.0.0.1/hook")

    def test_bare_ipv4_private_rejected(self):
        """https://192.168.1.1/... is rejected as a bare IP."""
        with pytest.raises(ValueError, match="bare IP address"):
            validate_webhook_url("https://192.168.1.1/hook")

    def test_bare_public_ipv4_rejected(self):
        """https://8.8.8.8/... is rejected as a bare IP (must use hostname)."""
        with pytest.raises(ValueError, match="bare IP address"):
            validate_webhook_url("https://8.8.8.8/hook")

    def test_bare_ipv6_loopback_rejected(self):
        """https://[::1]/... is rejected as a bare IP."""
        with pytest.raises(ValueError, match="bare IP address"):
            validate_webhook_url("https://[::1]/hook")

    def test_bare_ipv6_link_local_rejected(self):
        """https://[fe80::1]/... is rejected as a bare IP."""
        with pytest.raises(ValueError, match="bare IP address"):
            validate_webhook_url("https://[fe80::1]/hook")


# ---------------------------------------------------------------------------
# validate_webhook_url — blocked private/internal ranges
# ---------------------------------------------------------------------------


class TestBlockedNetworks:
    """Hostnames that resolve to blocked IP ranges must be rejected."""

    def _mock_dns(self, ip: str):
        """Return a getaddrinfo mock that resolves to a single IP."""
        return [(None, None, None, None, (ip, 0))]

    def test_loopback_127_0_0_1_blocked(self):
        """Hostname resolving to 127.0.0.1 (loopback) is rejected."""
        with patch("socket.getaddrinfo", return_value=self._mock_dns("127.0.0.1")):
            with pytest.raises(ValueError, match="blocked IP address"):
                validate_webhook_url("https://internal.example.com/hook")

    def test_loopback_127_1_2_3_blocked(self):
        """Any 127.x.x.x address is in the loopback /8 and is rejected."""
        with patch("socket.getaddrinfo", return_value=self._mock_dns("127.1.2.3")):
            with pytest.raises(ValueError, match="blocked IP address"):
                validate_webhook_url("https://internal.example.com/hook")

    def test_ipv6_loopback_blocked(self):
        """Hostname resolving to ::1 (IPv6 loopback) is rejected."""
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("::1", 0, 0, 0))]):
            with pytest.raises(ValueError, match="blocked IP address"):
                validate_webhook_url("https://internal.example.com/hook")

    def test_link_local_169_254_blocked(self):
        """Hostname resolving to 169.254.x.x (link-local / cloud metadata) is rejected."""
        with patch("socket.getaddrinfo", return_value=self._mock_dns("169.254.169.254")):
            with pytest.raises(ValueError, match="blocked IP address"):
                validate_webhook_url("https://metadata.internal/hook")

    def test_rfc1918_10_x_x_x_blocked(self):
        """Hostname resolving to 10.x.x.x (RFC-1918) is rejected."""
        with patch("socket.getaddrinfo", return_value=self._mock_dns("10.0.0.1")):
            with pytest.raises(ValueError, match="blocked IP address"):
                validate_webhook_url("https://internal.example.com/hook")

    def test_rfc1918_172_16_x_x_blocked(self):
        """Hostname resolving to 172.16.x.x (RFC-1918) is rejected."""
        with patch("socket.getaddrinfo", return_value=self._mock_dns("172.16.0.1")):
            with pytest.raises(ValueError, match="blocked IP address"):
                validate_webhook_url("https://internal.example.com/hook")

    def test_rfc1918_192_168_x_x_blocked(self):
        """Hostname resolving to 192.168.x.x (RFC-1918) is rejected."""
        with patch("socket.getaddrinfo", return_value=self._mock_dns("192.168.1.100")):
            with pytest.raises(ValueError, match="blocked IP address"):
                validate_webhook_url("https://internal.example.com/hook")

    def test_docker_bridge_172_17_blocked(self):
        """Hostname resolving to 172.17.x.x (Docker bridge) is rejected."""
        with patch("socket.getaddrinfo", return_value=self._mock_dns("172.17.0.1")):
            with pytest.raises(ValueError, match="blocked IP address"):
                validate_webhook_url("https://docker-internal.example.com/hook")

    def test_ipv6_link_local_fe80_blocked(self):
        """Hostname resolving to fe80:: (IPv6 link-local) is rejected."""
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("fe80::1", 0, 0, 0))]):
            with pytest.raises(ValueError, match="blocked IP address"):
                validate_webhook_url("https://linklocal.example.com/hook")

    def test_public_ip_passes(self):
        """Hostname resolving to a public IP passes validation."""
        with patch("socket.getaddrinfo", return_value=self._mock_dns("93.184.216.34")):
            result = validate_webhook_url("https://example.com/hook")
        assert result == "https://example.com/hook"

    def test_one_blocked_ip_among_many_rejects(self):
        """If any resolved IP is blocked, the whole URL is rejected."""
        # Simulate a round-robin DNS that returns both a public and a private IP.
        addr_infos = [
            (None, None, None, None, ("93.184.216.34", 0)),  # public — OK
            (None, None, None, None, ("10.0.0.5", 0)),  # private — BLOCKED
        ]
        with patch("socket.getaddrinfo", return_value=addr_infos):
            with pytest.raises(ValueError, match="blocked IP address"):
                validate_webhook_url("https://sneaky.example.com/hook")

    def test_dns_resolution_failure_raises(self):
        """Unresolvable hostname raises ValueError (not OSError)."""
        import socket as _socket

        with patch("socket.getaddrinfo", side_effect=_socket.gaierror("NXDOMAIN")):
            with pytest.raises(ValueError, match="could not be resolved"):
                validate_webhook_url("https://no-such-host-xyz.example.com/hook")


# ---------------------------------------------------------------------------
# Schema validators — WebhookCreateRequest
# ---------------------------------------------------------------------------


class TestWebhookCreateRequestUrlValidator:
    """URL field_validator on WebhookCreateRequest must block SSRF URLs."""

    def test_valid_https_url_accepted(self):
        """Valid https URL passes schema validation."""
        from src.api.schemas.webhooks import WebhookCreateRequest

        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))]):
            req = WebhookCreateRequest(
                url="https://example.com/hook",
                events=["backtest.completed"],
            )
        assert req.url == "https://example.com/hook"

    def test_http_url_rejected_by_schema(self):
        """http:// URL raises Pydantic ValidationError on WebhookCreateRequest."""
        from pydantic import ValidationError

        from src.api.schemas.webhooks import WebhookCreateRequest

        with pytest.raises(ValidationError, match="https scheme"):
            WebhookCreateRequest(
                url="http://example.com/hook",
                events=["backtest.completed"],
            )

    def test_private_ip_hostname_rejected_by_schema(self):
        """Hostname resolving to private IP raises ValidationError."""
        from pydantic import ValidationError

        from src.api.schemas.webhooks import WebhookCreateRequest

        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("192.168.1.1", 0))]):
            with pytest.raises(ValidationError, match="blocked IP address"):
                WebhookCreateRequest(
                    url="https://internal.corp/hook",
                    events=["backtest.completed"],
                )

    def test_bare_ip_rejected_by_schema(self):
        """Bare IP URL raises ValidationError."""
        from pydantic import ValidationError

        from src.api.schemas.webhooks import WebhookCreateRequest

        with pytest.raises(ValidationError, match="bare IP address"):
            WebhookCreateRequest(
                url="https://10.0.0.1/hook",
                events=["backtest.completed"],
            )


# ---------------------------------------------------------------------------
# Schema validators — WebhookUpdateRequest
# ---------------------------------------------------------------------------


class TestWebhookUpdateRequestUrlValidator:
    """URL field_validator on WebhookUpdateRequest must block SSRF URLs."""

    def test_none_url_accepted(self):
        """url=None (optional on update) passes validation without DNS check."""
        from src.api.schemas.webhooks import WebhookUpdateRequest

        req = WebhookUpdateRequest(url=None)
        assert req.url is None

    def test_valid_https_url_accepted(self):
        """Valid https URL passes schema validation on update."""
        from src.api.schemas.webhooks import WebhookUpdateRequest

        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))]):
            req = WebhookUpdateRequest(url="https://example.com/hook/v2")
        assert req.url == "https://example.com/hook/v2"

    def test_http_url_rejected_by_update_schema(self):
        """http:// URL raises ValidationError on WebhookUpdateRequest."""
        from pydantic import ValidationError

        from src.api.schemas.webhooks import WebhookUpdateRequest

        with pytest.raises(ValidationError, match="https scheme"):
            WebhookUpdateRequest(url="http://evil.example.com/hook")

    def test_loopback_hostname_rejected_by_update_schema(self):
        """Loopback hostname raises ValidationError on WebhookUpdateRequest."""
        from pydantic import ValidationError

        from src.api.schemas.webhooks import WebhookUpdateRequest

        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))]):
            with pytest.raises(ValidationError, match="blocked IP address"):
                WebhookUpdateRequest(url="https://localhost.corp/hook")


# ---------------------------------------------------------------------------
# Defence-in-depth: _async_dispatch SSRF check
# ---------------------------------------------------------------------------


class TestAsyncDispatchSsrfBlock:
    """_async_dispatch must silently drop delivery when URL fails SSRF check."""

    def _make_task(self):
        task = MagicMock()
        task.request = MagicMock()
        task.request.retries = 0
        task.retry = MagicMock(side_effect=Exception("retry_sentinel"))
        return task

    def _make_session_factory_with_secret(self, secret: str = "test-secret"):
        """Return a session factory mock that yields a row with the given secret.

        The session's execute() is pre-wired to return a result object whose
        one_or_none() gives back a row with the provided secret.  We do NOT
        patch ``WebhookSubscription`` because SQLAlchemy's ``select()`` call
        tries to introspect column attributes on that class — a plain MagicMock
        will cause ArgumentError there.  Instead we allow the real model class
        to be imported but have the DB layer return our fake row without ever
        executing real SQL.
        """
        row = MagicMock()
        row.secret = secret

        result = MagicMock()
        result.one_or_none.return_value = row

        session = AsyncMock()
        # Make execute() accept any argument and return the fake result.
        session.execute = AsyncMock(return_value=result)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        factory = MagicMock(return_value=ctx)
        return factory

    async def test_ssrf_blocked_url_skips_http_post(self):
        """When validate_webhook_url raises, httpx.post is never called."""
        mock_factory = self._make_session_factory_with_secret()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch(
                "src.webhooks.dispatcher.validate_webhook_url",
                side_effect=ValueError("blocked IP address"),
            ),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = self._make_task()
            result = await _async_dispatch(
                task=task,
                subscription_id=str(uuid4()),
                url="https://internal.example.com/hook",
                event_name="backtest.completed",
                payload={"test": True},
            )

        # No HTTP request should have been made.
        mock_client.post.assert_not_called()
        assert result["success"] is False
        assert result["status_code"] == 0

    async def test_ssrf_blocked_result_has_correct_shape(self):
        """SSRF-blocked result contains all expected keys."""
        mock_factory = self._make_session_factory_with_secret()
        sub_id = str(uuid4())

        with (
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("httpx.AsyncClient"),
            patch(
                "src.webhooks.dispatcher.validate_webhook_url",
                side_effect=ValueError("must use the https scheme"),
            ),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = self._make_task()
            result = await _async_dispatch(
                task=task,
                subscription_id=sub_id,
                url="http://internal.example.com/hook",
                event_name="battle.completed",
                payload={},
            )

        assert result["subscription_id"] == sub_id
        assert result["event_name"] == "battle.completed"
        assert result["status_code"] == 0
        assert result["duration_ms"] == 0
        assert result["success"] is False

    async def test_valid_url_proceeds_to_http_delivery(self):
        """When URL passes SSRF check, httpx.post is called normally."""
        mock_factory = self._make_session_factory_with_secret("mysecret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_record_success = AsyncMock()

        with (
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.webhooks.dispatcher.validate_webhook_url", return_value="https://example.com/hook"),
            patch("src.tasks.webhook_tasks._record_success", mock_record_success),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = self._make_task()
            result = await _async_dispatch(
                task=task,
                subscription_id=str(uuid4()),
                url="https://example.com/hook",
                event_name="backtest.completed",
                payload={"id": "abc"},
            )

        mock_client.post.assert_awaited_once()
        assert result["success"] is True
        assert result["status_code"] == 200
