"""Training run tracker that reports to the TradeReady training API."""

from __future__ import annotations

import logging
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class TrainingTracker:
    """Auto-reports training progress to the TradeReady platform.

    Creates a training run on the first episode, reports each episode's
    metrics, and finalizes the run on ``complete_run()``.

    Args:
        api_key:        TradeReady API key.
        base_url:       TradeReady REST API base URL.
        strategy_label: Optional label for the training run.
        strategy_id:    Optional linked strategy UUID.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
        strategy_label: str = "gym_training",
        strategy_id: str | None = None,
    ) -> None:
        self._api_key = api_key
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Invalid base_url: {base_url!r}")
        self._base_url = base_url.rstrip("/")
        self._strategy_label = strategy_label
        self._strategy_id = strategy_id
        self._run_id: str = str(uuid.uuid4())
        self._registered: bool = False
        self._completed: bool = False
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=15.0,
            headers={"X-API-Key": self._api_key},
        )

    @property
    def run_id(self) -> str:
        """The UUID for the current training run."""
        return self._run_id

    def register_run(self) -> None:
        """Register the training run with the platform API."""
        if self._registered:
            return
        try:
            body: dict[str, Any] = {
                "run_id": self._run_id,
                "config": {"strategy_label": self._strategy_label},
            }
            if self._strategy_id:
                body["strategy_id"] = self._strategy_id
            self._http.post("/api/v1/training/runs", json=body)
            self._registered = True
            logger.info("Registered training run %s", self._run_id)
        except Exception:
            logger.warning("Failed to register training run %s", self._run_id, exc_info=False)

    def report_episode(
        self,
        episode_number: int,
        session_id: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        """Report a completed episode to the training API."""
        if not self._registered:
            self.register_run()
        try:
            body: dict[str, Any] = {"episode_number": episode_number}
            if session_id:
                body["session_id"] = session_id
            if metrics:
                body["roi_pct"] = metrics.get("roi_pct")
                body["sharpe_ratio"] = metrics.get("sharpe_ratio")
                body["max_drawdown_pct"] = metrics.get("max_drawdown_pct")
                body["total_trades"] = metrics.get("total_trades")
                body["reward_sum"] = metrics.get("reward_sum")
            self._http.post(f"/api/v1/training/runs/{self._run_id}/episodes", json=body)
        except Exception:
            logger.warning(
                "Failed to report episode %d for run %s",
                episode_number,
                self._run_id,
                exc_info=False,
            )

    def complete_run(self) -> None:
        """Mark the training run as completed."""
        if self._completed or not self._registered:
            return
        try:
            self._http.post(f"/api/v1/training/runs/{self._run_id}/complete")
            self._completed = True
            logger.info("Completed training run %s", self._run_id)
        except Exception:
            logger.warning("Failed to complete training run %s", self._run_id, exc_info=False)
        finally:
            self._http.close()

    # No __del__: callers must call env.close() which calls complete_run().
    # __del__ is unreliable during interpreter shutdown and can cause errors
    # when httpx.Client is already closed.
