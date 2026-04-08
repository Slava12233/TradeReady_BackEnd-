"""Webhook integration example: receive backtest completion events.

Demonstrates how to use the TradeReady webhook system to receive real-time
event notifications instead of polling:
  1. Start a local HTTP server to receive webhook payloads (port 9000 by default)
  2. Register a webhook subscription for the 'backtest.completed' event
  3. Trigger a backtest via fast-batch stepping
  4. Block until the webhook event arrives (or timeout)
  5. Validate the HMAC-SHA256 signature to ensure the payload is genuine
  6. Print the event payload and clean up

The webhook approach is useful when running long backtests or strategy tests
where polling would waste resources.  In production, replace the local server
with your own HTTPS endpoint.

Note:
    The local HTTP server binds to 127.0.0.1 — the platform must be running on
    the same machine for it to reach this endpoint.  For remote platforms, use
    ngrok or a similar tunnelling tool to expose the local port.

Requirements:
    pip install -e sdk/
    export TRADEREADY_API_URL=http://localhost:8000
    export TRADEREADY_API_KEY=ak_live_YOUR_KEY
    export TRADEREADY_API_SECRET=sk_live_YOUR_SECRET

Run:
    python sdk/examples/webhook_integration.py
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from agentexchange import AgentExchangeClient
from agentexchange.exceptions import AgentExchangeError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("TRADEREADY_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("TRADEREADY_API_KEY", "")
API_SECRET = os.environ.get("TRADEREADY_API_SECRET", "")

WEBHOOK_PORT = int(os.environ.get("TRADEREADY_WEBHOOK_PORT", "9000"))
WEBHOOK_PATH = "/hooks/tradeready"
WAIT_TIMEOUT = 120   # seconds to wait for the webhook event before giving up

# Global state shared between the HTTP server thread and the main thread
_received_event: dict[str, Any] | None = None
_event_lock = threading.Lock()
_event_ready = threading.Event()
_webhook_secret: str = ""


def _require_env() -> None:
    """Verify required environment variables are set before proceeding."""
    missing = [v for v in ("TRADEREADY_API_KEY", "TRADEREADY_API_SECRET") if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing environment variable(s): {', '.join(missing)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Local webhook receiver
# ---------------------------------------------------------------------------

class _WebhookHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that accepts POST requests on WEBHOOK_PATH.

    Validates the HMAC-SHA256 signature in the ``X-TradeReady-Signature``
    header before accepting the payload.  Stores the validated event in the
    global ``_received_event`` dict and signals ``_event_ready``.
    """

    def do_POST(self) -> None:  # noqa: N802 — stdlib naming convention
        """Handle incoming webhook POST requests."""
        if self.path != WEBHOOK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        # Validate HMAC-SHA256 signature
        sig_header = self.headers.get("X-TradeReady-Signature", "")
        if _webhook_secret and sig_header:
            expected = hmac.new(
                _webhook_secret.encode(),
                body,
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(sig_header, f"sha256={expected}"):
                print("  WARNING: Webhook signature mismatch — rejecting payload.")
                self.send_response(401)
                self.end_headers()
                return

        # Parse and store the event
        try:
            payload: dict[str, Any] = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        with _event_lock:
            global _received_event
            _received_event = payload

        _event_ready.set()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Suppress default access log noise to keep output clean."""
        # Only log non-200 responses
        if args and str(args[1]) != "200":
            super().log_message(format, *args)


def _start_server() -> HTTPServer:
    """Start the local webhook receiver in a background daemon thread.

    Returns:
        The running HTTPServer instance.
    """
    server = HTTPServer(("127.0.0.1", WEBHOOK_PORT), _WebhookHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Webhook receiver started at http://127.0.0.1:{WEBHOOK_PORT}{WEBHOOK_PATH}")
    return server


# ---------------------------------------------------------------------------
# Backtest helpers
# ---------------------------------------------------------------------------

def _create_and_run_backtest(client: AgentExchangeClient) -> str:
    """Create, start, and fast-batch step a short backtest to completion.

    Returns the session ID so the caller can correlate it with the webhook.

    Args:
        client: Authenticated SDK client.

    Returns:
        Completed backtest session ID.
    """
    print("\nCreating backtest session (7-day, BTCUSDT, 1-minute candles)...")
    response = client._request(
        "POST",
        "/api/v1/backtest/create",
        json={
            "start_time": "2025-01-01T00:00:00Z",
            "end_time": "2025-01-07T23:59:00Z",
            "starting_balance": "10000",
            "candle_interval": 60,
            "pairs": ["BTCUSDT"],
            "strategy_label": "webhook_example",
        },
    )
    session_id: str = response["session_id"]
    print(f"Session created: {session_id}")

    # Start the session
    client._request("POST", f"/api/v1/backtest/{session_id}/start")
    print("Session started. Running fast-batch steps to completion...")

    # Advance the simulation in large batches
    while True:
        result = client.batch_step_fast(session_id, steps=1000)
        progress = result.get("progress_pct", 0.0)
        print(f"  Progress: {progress:.1f}%")
        if result.get("is_complete"):
            break

    print("Backtest simulation complete.")
    return session_id


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------

def main() -> None:
    """Register a webhook, run a backtest, and receive the completion event."""
    global _webhook_secret

    _require_env()

    # Step 1 — Start the local webhook receiver
    server = _start_server()

    webhook_id: str | None = None

    with AgentExchangeClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        base_url=BASE_URL,
    ) as client:
        try:
            # Step 2 — Register a webhook subscription for backtest completion
            webhook_url = f"http://127.0.0.1:{WEBHOOK_PORT}{WEBHOOK_PATH}"
            print(f"\nRegistering webhook subscription -> {webhook_url}")

            wh = client.create_webhook(
                url=webhook_url,
                events=["backtest.completed"],
                description="SDK example webhook (backtest completion)",
            )
            webhook_id = wh["webhook_id"]
            # Store the signing secret so the handler can validate payloads
            _webhook_secret = wh.get("secret", "")
            print(f"Webhook registered: id={webhook_id}")
            if _webhook_secret:
                print("  HMAC-SHA256 signing secret stored (validation enabled).")
            else:
                print("  WARNING: No signing secret returned — signature validation disabled.")

            # Step 3 — Optionally verify the webhook is reachable
            print("\nSending test ping to verify endpoint connectivity...")
            try:
                ping = client.test_webhook(webhook_id)
                print(f"  Test ping enqueued: {ping.get('enqueued', 0)} event(s)")
                # Wait briefly for the test ping (not the real event)
                _event_ready.wait(timeout=5)
                _event_ready.clear()
                with _event_lock:
                    _received_event = None
            except AgentExchangeError as exc:
                print(f"  WARNING: test ping failed: {exc}")

            # Step 4 — Run the backtest (this triggers the 'backtest.completed' event)
            session_id = _create_and_run_backtest(client)

            # Step 5 — Wait for the webhook event
            print(f"\nWaiting up to {WAIT_TIMEOUT}s for 'backtest.completed' event...")
            received = _event_ready.wait(timeout=WAIT_TIMEOUT)

            if not received:
                print("TIMEOUT: Webhook event did not arrive within the timeout period.")
                print("  This can happen if the platform webhook worker is not running.")
            else:
                with _event_lock:
                    event = _received_event

                # Step 6 — Process the event payload
                print("\nWebhook event received!")
                print(f"  Event type  : {event.get('event', 'unknown')}")
                print(f"  Session ID  : {event.get('session_id', 'n/a')}")
                print(f"  Status      : {event.get('status', 'n/a')}")
                metrics = event.get("metrics") or {}
                if metrics:
                    print(f"  Total Return: {metrics.get('total_return_pct', 'n/a')}%")
                    print(f"  Sharpe Ratio: {metrics.get('sharpe_ratio', 'n/a')}")
                    print(f"  Max Drawdown: {metrics.get('max_drawdown_pct', 'n/a')}%")

                # Verify session ID matches what we created
                if event.get("session_id") == session_id:
                    print("\nSession ID matched — event is from our backtest.")
                else:
                    print(
                        f"\nWARNING: Session ID mismatch. "
                        f"Expected {session_id}, got {event.get('session_id')}."
                    )

        finally:
            # Step 7 — Clean up the webhook subscription
            if webhook_id is not None:
                try:
                    client.delete_webhook(webhook_id)
                    print(f"\nWebhook {webhook_id} deleted.")
                except AgentExchangeError as exc:
                    print(f"WARNING: Could not delete webhook: {exc}")

    # Shut down the local HTTP server
    server.shutdown()
    print("Webhook receiver stopped.")
    print("\nWebhook integration example complete.")


if __name__ == "__main__":
    main()
