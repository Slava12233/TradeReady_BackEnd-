"""Security regression tests for all R2-series fixes.

Tests ensure that critical security invariants introduced in R2-01 through R2-06
cannot be accidentally reverted:

- R2-01: ADMIN-only guard on grant_capability() and set_role()
- R2-02: BudgetManager.close() awaits all pending persist tasks
- R2-04: AgentAuditLogRepository.create() and bulk_create() persist entries
- R2-05: verify_checksum() blocks model load on digest mismatch or missing sidecar
- R2-06: joblib payload structure check rejects non-dict / missing-key payloads
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from src.database.models import AgentAuditLog
from src.database.repositories.agent_audit_log_repo import AgentAuditLogRepository

from agent.permissions.capabilities import Capability, CapabilityManager
from agent.permissions.enforcement import PermissionDenied
from agent.permissions.roles import AgentRole
from agent.strategies.checksum import SecurityError, save_checksum, verify_checksum

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_capability_manager(mock_redis: AsyncMock) -> CapabilityManager:
    """Return a CapabilityManager with a pre-injected mock Redis client."""
    config = MagicMock()
    config.default_agent_role = "viewer"
    return CapabilityManager(config=config, redis=mock_redis)


def _make_mock_session() -> AsyncMock:
    """Return a mock AsyncSession wired as an async context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.add = MagicMock()  # synchronous in SQLAlchemy
    session.add_all = MagicMock()  # synchronous in SQLAlchemy
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# R2-01 -- ADMIN role check on grant_capability()
# ---------------------------------------------------------------------------


class TestR201AdminRoleOnGrantCapability:
    """R2-01: grant_capability() must require ADMIN role from the grantor."""

    async def test_non_admin_grantor_raises_permission_denied(self) -> None:
        """A grantor with VIEWER role cannot grant capabilities -- raises PermissionDenied."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.delete = AsyncMock()

        manager = _make_capability_manager(mock_redis)

        agent_id = str(uuid4())
        grantor_id = str(uuid4())

        with patch.object(manager, "get_role", new=AsyncMock(return_value=AgentRole.VIEWER)):
            with pytest.raises(PermissionDenied) as exc_info:
                await manager.grant_capability(agent_id, Capability.CAN_TRADE, granted_by=grantor_id)

        assert exc_info.value.action == "grant_capability"
        assert "ADMIN" in exc_info.value.reason or "viewer" in exc_info.value.reason.lower()

    async def test_paper_trader_grantor_raises_permission_denied(self) -> None:
        """A PAPER_TRADER grantor cannot grant capabilities -- raises PermissionDenied."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.delete = AsyncMock()

        manager = _make_capability_manager(mock_redis)

        agent_id = str(uuid4())
        grantor_id = str(uuid4())

        with patch.object(manager, "get_role", new=AsyncMock(return_value=AgentRole.PAPER_TRADER)):
            with pytest.raises(PermissionDenied):
                await manager.grant_capability(agent_id, Capability.CAN_BACKTEST, granted_by=grantor_id)

    async def test_admin_grantor_proceeds_to_db_write(self) -> None:
        """An ADMIN grantor passes the role check and proceeds to write the DB."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.delete = AsyncMock()

        manager = _make_capability_manager(mock_redis)

        agent_id = str(uuid4())
        grantor_id = str(uuid4())

        mock_session = _make_mock_session()
        mock_session.begin = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        mock_repo = AsyncMock()
        from src.database.repositories.agent_permission_repo import (  # noqa: PLC0415
            AgentPermissionNotFoundError,
        )

        mock_repo.get_by_agent = AsyncMock(side_effect=AgentPermissionNotFoundError)
        mock_repo.upsert = AsyncMock()

        with (
            patch.object(manager, "get_role", new=AsyncMock(return_value=AgentRole.ADMIN)),
            patch.object(manager, "_get_db_session", new=AsyncMock(return_value=mock_session)),
            patch(
                "src.database.repositories.agent_permission_repo.AgentPermissionRepository",
                return_value=mock_repo,
            ),
        ):
            # Should not raise
            await manager.grant_capability(agent_id, Capability.CAN_TRADE, granted_by=grantor_id)

        mock_repo.upsert.assert_called_once()


# ---------------------------------------------------------------------------
# R2-01 -- ADMIN role check on set_role()
# ---------------------------------------------------------------------------


class TestR201AdminRoleOnSetRole:
    """R2-01: set_role() must require ADMIN role from the grantor."""

    async def test_non_admin_grantor_set_role_raises_permission_denied(self) -> None:
        """A non-ADMIN grantor cannot change agent roles -- raises PermissionDenied."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.delete = AsyncMock()

        manager = _make_capability_manager(mock_redis)

        agent_id = str(uuid4())
        grantor_id = str(uuid4())

        with patch.object(manager, "get_role", new=AsyncMock(return_value=AgentRole.LIVE_TRADER)):
            with pytest.raises(PermissionDenied) as exc_info:
                await manager.set_role(agent_id, AgentRole.ADMIN, granted_by=grantor_id)

        assert exc_info.value.action == "set_role"

    async def test_admin_grantor_set_role_proceeds(self) -> None:
        """An ADMIN grantor can change roles without raising."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.delete = AsyncMock()

        manager = _make_capability_manager(mock_redis)

        agent_id = str(uuid4())
        grantor_id = str(uuid4())

        mock_session = _make_mock_session()
        mock_session.begin = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        mock_repo = AsyncMock()
        from src.database.repositories.agent_permission_repo import (  # noqa: PLC0415
            AgentPermissionNotFoundError,
        )

        mock_repo.get_by_agent = AsyncMock(side_effect=AgentPermissionNotFoundError)
        mock_repo.upsert = AsyncMock()

        with (
            patch.object(manager, "get_role", new=AsyncMock(return_value=AgentRole.ADMIN)),
            patch.object(manager, "_get_db_session", new=AsyncMock(return_value=mock_session)),
            patch(
                "src.database.repositories.agent_permission_repo.AgentPermissionRepository",
                return_value=mock_repo,
            ),
        ):
            # Must not raise
            await manager.set_role(agent_id, AgentRole.LIVE_TRADER, granted_by=grantor_id)

        mock_repo.upsert.assert_called_once()


# ---------------------------------------------------------------------------
# R2-02 -- BudgetManager.close() awaits pending tasks
# ---------------------------------------------------------------------------


class TestR202BudgetManagerClose:
    """R2-02: BudgetManager.close() must await all pending persist tasks."""

    async def test_close_awaits_pending_tasks(self) -> None:
        """close() awaits every task in _pending_persists and the tasks complete."""
        from agent.permissions.budget import BudgetManager  # noqa: PLC0415

        config = MagicMock()
        config.default_max_trades_per_day = 50
        config.default_max_exposure_pct = 80.0
        config.default_max_daily_loss_pct = 10.0

        manager = BudgetManager(config=config)

        async def _noop() -> None:
            return None

        task1 = asyncio.create_task(_noop())
        task2 = asyncio.create_task(_noop())

        manager._pending_persists.add(task1)
        manager._pending_persists.add(task2)

        await manager.close()

        assert task1.done()
        assert task2.done()

    async def test_close_is_noop_when_no_pending_tasks(self) -> None:
        """close() is a safe no-op when there are no pending persist tasks."""
        from agent.permissions.budget import BudgetManager  # noqa: PLC0415

        config = MagicMock()
        config.default_max_trades_per_day = 50
        config.default_max_exposure_pct = 80.0
        config.default_max_daily_loss_pct = 10.0

        manager = BudgetManager(config=config)
        assert not manager._pending_persists

        # Must not raise.
        await manager.close()

    async def test_close_swallows_task_exceptions(self) -> None:
        """close() logs but does not propagate exceptions from failing persist tasks."""
        from agent.permissions.budget import BudgetManager  # noqa: PLC0415

        config = MagicMock()
        config.default_max_trades_per_day = 50
        config.default_max_exposure_pct = 80.0
        config.default_max_daily_loss_pct = 10.0

        manager = BudgetManager(config=config)

        async def _failing() -> None:
            raise RuntimeError("DB unreachable")

        task = asyncio.create_task(_failing())
        # Yield control so the task can start and raise before we gather.
        await asyncio.sleep(0)

        manager._pending_persists.add(task)

        # Must not propagate the RuntimeError.
        await manager.close()


# ---------------------------------------------------------------------------
# R2-04 -- AgentAuditLog repository persistence
# ---------------------------------------------------------------------------


class TestR204AuditLogRepository:
    """R2-04: AgentAuditLogRepository must persist allow and deny audit entries."""

    async def test_create_persists_allow_entry(self) -> None:
        """create() calls session.add() and flush() for an allow-outcome entry."""
        mock_session = _make_mock_session()

        repo = AgentAuditLogRepository(mock_session)

        entry = AgentAuditLog(
            agent_id=uuid4(),
            action="place_order",
            outcome="allow",
            reason=None,
        )
        returned = await repo.create(entry)

        mock_session.add.assert_called_once_with(entry)
        mock_session.flush.assert_called_once()
        assert returned is entry

    async def test_create_persists_deny_entry(self) -> None:
        """create() correctly persists a deny-outcome entry."""
        mock_session = _make_mock_session()

        repo = AgentAuditLogRepository(mock_session)

        entry = AgentAuditLog(
            agent_id=uuid4(),
            action="grant_capability",
            outcome="deny",
            reason="Grantor is viewer, not ADMIN",
        )
        returned = await repo.create(entry)

        mock_session.add.assert_called_once_with(entry)
        mock_session.flush.assert_called_once()
        assert returned is entry

    async def test_bulk_create_persists_multiple_entries(self) -> None:
        """bulk_create() calls add_all() and flush() for a batch of entries."""
        mock_session = _make_mock_session()
        repo = AgentAuditLogRepository(mock_session)

        agent_id = uuid4()
        entries = [
            AgentAuditLog(agent_id=agent_id, action="place_order", outcome="allow"),
            AgentAuditLog(agent_id=agent_id, action="create_backtest", outcome="deny", reason="budget"),
            AgentAuditLog(agent_id=agent_id, action="trade", outcome="allow"),
        ]

        count = await repo.bulk_create(entries)

        mock_session.add_all.assert_called_once_with(entries)
        mock_session.flush.assert_called_once()
        assert count == 3

    async def test_bulk_create_empty_list_returns_zero_without_db_call(self) -> None:
        """bulk_create() with an empty list returns 0 and skips all DB calls."""
        mock_session = _make_mock_session()
        repo = AgentAuditLogRepository(mock_session)

        count = await repo.bulk_create([])

        mock_session.add_all.assert_not_called()
        mock_session.flush.assert_not_called()
        assert count == 0


# ---------------------------------------------------------------------------
# R2-05 -- verify_checksum() blocks model load on mismatch / missing sidecar
# ---------------------------------------------------------------------------


class TestR205ChecksumVerification:
    """R2-05: verify_checksum() must raise SecurityError on mismatch or missing sidecar."""

    def test_verify_returns_true_on_matching_checksum(self, tmp_path: pytest.TempPathFactory) -> None:
        """verify_checksum() returns True when the digest matches the sidecar."""
        model_file = tmp_path / "model.zip"  # type: ignore[operator]
        model_file.write_bytes(b"fake model content for regression test")

        sidecar = save_checksum(model_file)
        assert sidecar.exists()

        result = verify_checksum(model_file)
        assert result is True

    def test_verify_raises_security_error_on_digest_mismatch(self, tmp_path: pytest.TempPathFactory) -> None:
        """verify_checksum() raises SecurityError when the file was tampered with."""
        model_file = tmp_path / "model.joblib"  # type: ignore[operator]
        model_file.write_bytes(b"original model bytes")

        save_checksum(model_file)

        # Tamper with the file after saving the sidecar.
        model_file.write_bytes(b"tampered model bytes - different content")

        with pytest.raises(SecurityError, match="Checksum mismatch"):
            verify_checksum(model_file)

    def test_verify_strict_true_raises_security_error_on_missing_sidecar(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """verify_checksum(strict=True) raises SecurityError when no sidecar exists."""
        model_file = tmp_path / "no_sidecar_model.zip"  # type: ignore[operator]
        model_file.write_bytes(b"model without any sidecar")

        # No call to save_checksum, so no .sha256 sidecar exists.
        with pytest.raises(SecurityError):
            verify_checksum(model_file, strict=True)

    def test_verify_strict_false_returns_true_on_missing_sidecar(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """verify_checksum(strict=False) returns True (with WARNING) when no sidecar."""
        model_file = tmp_path / "legacy_model.joblib"  # type: ignore[operator]
        model_file.write_bytes(b"pre-checksum legacy model artifact")

        # No sidecar; strict=False is the backwards-compat development mode.
        result = verify_checksum(model_file, strict=False)
        assert result is True

    def test_verify_detects_sidecar_swap(self, tmp_path: pytest.TempPathFactory) -> None:
        """verify_checksum() raises SecurityError when a different file's sidecar is used."""
        model_a = tmp_path / "model_a.zip"  # type: ignore[operator]
        model_b = tmp_path / "model_b.zip"  # type: ignore[operator]
        model_a.write_bytes(b"model A content")
        model_b.write_bytes(b"model B content - entirely different")

        # Save checksum for model_a, then copy it to model_b's expected sidecar path.
        save_checksum(model_a)
        sidecar_a = model_a.with_suffix(".zip.sha256")
        sidecar_b = model_b.with_suffix(".zip.sha256")
        sidecar_b.write_text(sidecar_a.read_text())

        # model_b now has model_a's digest as its sidecar -- mismatch.
        with pytest.raises(SecurityError):
            verify_checksum(model_b)


# ---------------------------------------------------------------------------
# R2-06 -- joblib payload structure check
# ---------------------------------------------------------------------------


class TestR206JoblibStructureCheck:
    """R2-06: RegimeClassifier.load() must reject invalid joblib payloads."""

    def test_valid_payload_dict_with_model_key_passes(self, tmp_path: pytest.TempPathFactory) -> None:
        """A well-formed payload dict passes the structure check and is accepted."""
        joblib = pytest.importorskip("joblib")

        model_file = tmp_path / "classifier.joblib"  # type: ignore[operator]

        # label_encoder is dict[str, int] as produced by RegimeClassifier.train().
        import numpy as np  # noqa: PLC0415
        from sklearn.dummy import DummyClassifier  # noqa: PLC0415

        clf = DummyClassifier(strategy="most_frequent")
        clf.fit(np.array([[0.1, 0.2, 0.3, 0.4, 0.5, 0.6]]), [0])

        payload = {
            "model": clf,
            "label_encoder": {"TRENDING": 0, "MEAN_REVERTING": 1},
            "label_decoder": {0: "TRENDING", 1: "MEAN_REVERTING"},
            "feature_names": ["adx", "atr_ratio", "bb_width", "rsi", "macd_hist", "volume_ratio"],
            "seed": 42,
            "backend": "random_forest",
        }
        joblib.dump(payload, model_file)
        save_checksum(model_file)

        from agent.strategies.regime.classifier import RegimeClassifier  # noqa: PLC0415

        loaded = RegimeClassifier.load(model_file)
        assert loaded is not None

    def test_non_dict_payload_raises_value_error(self, tmp_path: pytest.TempPathFactory) -> None:
        """A joblib file containing a list instead of dict raises ValueError."""
        joblib = pytest.importorskip("joblib")

        model_file = tmp_path / "bad_payload.joblib"  # type: ignore[operator]
        joblib.dump([1, 2, 3], model_file)
        save_checksum(model_file)

        from agent.strategies.regime.classifier import RegimeClassifier  # noqa: PLC0415

        with pytest.raises(ValueError, match="expected dict"):
            RegimeClassifier.load(model_file)

    def test_dict_missing_required_key_raises_value_error(self, tmp_path: pytest.TempPathFactory) -> None:
        """A dict payload missing required keys raises ValueError."""
        joblib = pytest.importorskip("joblib")

        model_file = tmp_path / "incomplete_payload.joblib"  # type: ignore[operator]
        # "model" key is present but several required keys are missing.
        joblib.dump({"model": None, "backend": "xgboost"}, model_file)
        save_checksum(model_file)

        from agent.strategies.regime.classifier import RegimeClassifier  # noqa: PLC0415

        with pytest.raises(ValueError, match="missing required keys"):
            RegimeClassifier.load(model_file)
