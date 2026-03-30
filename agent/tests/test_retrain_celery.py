"""Integration tests for src/tasks/retrain_tasks.py — Celery retraining task bridge.

Celery is not installed in the test environment, so we:
  1. Inject a minimal Celery stub into sys.modules before importing src.tasks.*
  2. Test the _*_async functions directly (they run RetrainOrchestrator calls)
  3. Use AST inspection for structural assertions (lazy imports, task decorators)

Coverage:
  - All five tasks are registered on the stub Celery app with correct names
  - All five tasks have soft_time_limit=3600 and time_limit=3900
  - All five tasks have max_retries=0 and ignore_result=False
  - All five tasks are in the ml_training queue
  - Beat schedule has entries for all five retrain tasks
  - Each entry routes to ml_training queue
  - No top-level agent.strategies imports in retrain_tasks.py (lazy import guard)
  - _retrain_ensemble_async calls orchestrator.retrain_ensemble()
  - _retrain_regime_async calls orchestrator.retrain_regime()
  - _retrain_genome_async calls orchestrator.retrain_genome()
  - _retrain_rl_async calls orchestrator.retrain_rl()
  - _run_retraining_cycle_async calls orchestrator.run_scheduled_cycle()
  - duration_ms is injected into the returned dict
  - Exceptions from orchestrator propagate through async bridge
  - RetrainResult.to_log_dict() output is included in return value
"""

from __future__ import annotations

import ast
import sys
import types
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Celery stub — injected once per session before any src.tasks.* import
# ---------------------------------------------------------------------------


class _FakeConf:
    """Minimal stub for Celery app.conf."""

    def __init__(self) -> None:
        self.beat_schedule: dict[str, Any] = {}
        self.task_routes: dict[str, Any] = {}
        self.task_queues: tuple[object, ...] = ()
        self.task_default_queue: str = "default"

    def update(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeCelery:
    """Minimal stub for the Celery application class."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.tasks: dict[str, Any] = {}
        self.conf = _FakeConf()

    def task(self, *_args: object, **kwargs: object) -> Any:  # noqa: ANN401
        captured = dict(kwargs)

        def decorator(fn: Any) -> Any:  # noqa: ANN401
            name = str(captured.get("name", fn.__name__))
            fn.celery_task_name = name
            fn.soft_time_limit = captured.get("soft_time_limit")
            fn.time_limit = captured.get("time_limit")
            fn.max_retries = captured.get("max_retries", 3)
            fn.ignore_result = captured.get("ignore_result", True)
            fn.queue = captured.get("queue")
            self.tasks[name] = fn
            return fn

        return decorator


class _FakeQueue:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass


def _inject_celery_stubs() -> None:
    """Inject fake celery/kombu modules so src.tasks.celery_app can be imported."""
    if "celery" not in sys.modules:
        celery_mod = types.ModuleType("celery")
        celery_mod.Celery = _FakeCelery  # type: ignore[attr-defined]
        sys.modules["celery"] = celery_mod

    if "celery.schedules" not in sys.modules:
        schedules_mod = types.ModuleType("celery.schedules")
        schedules_mod.crontab = lambda **kw: f"crontab({kw})"  # type: ignore[attr-defined]
        sys.modules["celery.schedules"] = schedules_mod

    if "kombu" not in sys.modules:
        kombu_mod = types.ModuleType("kombu")
        kombu_mod.Queue = _FakeQueue  # type: ignore[attr-defined]
        sys.modules["kombu"] = kombu_mod


# Inject stubs at collection time so any import below this point can succeed.
_inject_celery_stubs()


# ---------------------------------------------------------------------------
# Helpers — lazy import of src.tasks modules after stubs are in place
# ---------------------------------------------------------------------------


def _get_celery_app() -> _FakeCelery:
    """Return the stub Celery app with all retrain tasks registered.

    Importing celery_app alone only loads the app and beat schedule.  The
    @app.task decorators in retrain_tasks.py only fire when retrain_tasks is
    imported, so we must import both modules.
    """
    import importlib  # noqa: PLC0415

    if "src.tasks.celery_app" not in sys.modules:
        importlib.import_module("src.tasks.celery_app")

    # Ensure retrain_tasks has been imported so its @app.task decorators fire.
    if "src.tasks.retrain_tasks" not in sys.modules:
        importlib.import_module("src.tasks.retrain_tasks")

    return sys.modules["src.tasks.celery_app"].app  # type: ignore[return-value]


def _make_retrain_result(
    component: str = "ensemble",
    *,
    success: bool = True,
    deployed: bool = True,
    improvement: float = 0.05,
) -> MagicMock:
    """Return a mock RetrainResult with to_log_dict() wired."""
    result = MagicMock()
    result.component = component
    result.success = success
    result.deployed = deployed
    log_dict: dict[str, Any] = {
        "component": component,
        "triggered_at": "2026-03-23T00:00:00Z",
        "completed_at": "2026-03-23T00:01:00Z",
        "success": success,
        "deployed": deployed,
        "improvement": improvement,
        "metric": "sharpe",
        "artifact_path": None,
        "error": None,
    }
    result.to_log_dict.return_value = log_dict
    return result


def _make_orchestrator(
    *,
    cycle_results: list[MagicMock] | None = None,
    ensemble_result: MagicMock | None = None,
    regime_result: MagicMock | None = None,
    genome_result: MagicMock | None = None,
    rl_result: MagicMock | None = None,
) -> MagicMock:
    """Return a mock RetrainOrchestrator with all async methods wired."""
    orc = MagicMock()
    orc.run_scheduled_cycle = AsyncMock(
        return_value=cycle_results or [_make_retrain_result("ensemble")]
    )
    orc.retrain_ensemble = AsyncMock(
        return_value=ensemble_result or _make_retrain_result("ensemble")
    )
    orc.retrain_regime = AsyncMock(
        return_value=regime_result or _make_retrain_result("regime")
    )
    orc.retrain_genome = AsyncMock(
        return_value=genome_result or _make_retrain_result("genome")
    )
    orc.retrain_rl = AsyncMock(
        return_value=rl_result or _make_retrain_result("rl")
    )
    return orc


def _patch_retrain_module(
    orchestrator: MagicMock,
) -> AbstractContextManager[dict[str, MagicMock]]:
    """Return a patch.multiple context manager that stubs agent.strategies.retrain."""
    mock_config = MagicMock()
    return patch.multiple(  # type: ignore[return-value]
        "agent.strategies.retrain",
        RetrainConfig=MagicMock(return_value=mock_config),
        RetrainOrchestrator=MagicMock(return_value=orchestrator),
    )


# ---------------------------------------------------------------------------
# Task registration tests
# ---------------------------------------------------------------------------


_ALL_TASK_NAMES = [
    "src.tasks.retrain_tasks.run_retraining_cycle",
    "src.tasks.retrain_tasks.retrain_ensemble",
    "src.tasks.retrain_tasks.retrain_regime",
    "src.tasks.retrain_tasks.retrain_genome",
    "src.tasks.retrain_tasks.retrain_rl",
]


class TestTaskRegistration:
    """All five retrain tasks must be registered on the Celery app."""

    def test_run_retraining_cycle_is_registered(self) -> None:
        """run_retraining_cycle is in the Celery task registry."""
        app = _get_celery_app()
        assert "src.tasks.retrain_tasks.run_retraining_cycle" in app.tasks

    def test_retrain_ensemble_is_registered(self) -> None:
        """retrain_ensemble is in the Celery task registry."""
        app = _get_celery_app()
        assert "src.tasks.retrain_tasks.retrain_ensemble" in app.tasks

    def test_retrain_regime_is_registered(self) -> None:
        """retrain_regime is in the Celery task registry."""
        app = _get_celery_app()
        assert "src.tasks.retrain_tasks.retrain_regime" in app.tasks

    def test_retrain_genome_is_registered(self) -> None:
        """retrain_genome is in the Celery task registry."""
        app = _get_celery_app()
        assert "src.tasks.retrain_tasks.retrain_genome" in app.tasks

    def test_retrain_rl_is_registered(self) -> None:
        """retrain_rl is in the Celery task registry."""
        app = _get_celery_app()
        assert "src.tasks.retrain_tasks.retrain_rl" in app.tasks


# ---------------------------------------------------------------------------
# Task option / constraint tests
# ---------------------------------------------------------------------------


class TestTaskOptions:
    """Task decorator parameters must match the architecture spec."""

    def test_soft_time_limit_is_3600_on_all_tasks(self) -> None:
        """All retrain tasks have soft_time_limit=3600 (1 h)."""
        app = _get_celery_app()
        for name in _ALL_TASK_NAMES:
            fn = app.tasks[name]
            assert fn.soft_time_limit == 3600, f"{name}: soft_time_limit should be 3600"

    def test_time_limit_is_3900_on_all_tasks(self) -> None:
        """All retrain tasks have time_limit=3900 (1 h 5 min)."""
        app = _get_celery_app()
        for name in _ALL_TASK_NAMES:
            fn = app.tasks[name]
            assert fn.time_limit == 3900, f"{name}: time_limit should be 3900"

    def test_max_retries_is_zero_on_all_tasks(self) -> None:
        """All retrain tasks have max_retries=0 (no automatic retry)."""
        app = _get_celery_app()
        for name in _ALL_TASK_NAMES:
            fn = app.tasks[name]
            assert fn.max_retries == 0, f"{name}: max_retries should be 0"

    def test_ignore_result_is_false_on_all_tasks(self) -> None:
        """All retrain tasks store their result (ignore_result=False)."""
        app = _get_celery_app()
        for name in _ALL_TASK_NAMES:
            fn = app.tasks[name]
            assert fn.ignore_result is False, f"{name}: ignore_result should be False"

    def test_queue_is_ml_training_on_all_tasks(self) -> None:
        """All retrain tasks are routed to the ml_training queue."""
        app = _get_celery_app()
        for name in _ALL_TASK_NAMES:
            fn = app.tasks[name]
            assert fn.queue == "ml_training", f"{name}: queue should be ml_training"


# ---------------------------------------------------------------------------
# Beat schedule tests
# ---------------------------------------------------------------------------


_BEAT_ENTRY_TASK_MAP: dict[str, str] = {
    "run-retraining-cycle": "src.tasks.retrain_tasks.run_retraining_cycle",
    "retrain-ensemble-weights": "src.tasks.retrain_tasks.retrain_ensemble",
    "retrain-regime-classifier": "src.tasks.retrain_tasks.retrain_regime",
    "retrain-genome-population": "src.tasks.retrain_tasks.retrain_genome",
    "retrain-rl-models": "src.tasks.retrain_tasks.retrain_rl",
}


class TestBeatSchedule:
    """All five retrain tasks must have beat schedule entries."""

    def test_all_retrain_beat_entries_exist(self) -> None:
        """Beat schedule contains all five retrain task entries."""
        app = _get_celery_app()
        for entry_name in _BEAT_ENTRY_TASK_MAP:
            assert entry_name in app.conf.beat_schedule, (
                f"Missing beat entry: '{entry_name}'"
            )

    def test_beat_entry_task_names_are_correct(self) -> None:
        """Each beat entry points to the correct task name."""
        app = _get_celery_app()
        for entry_name, task_name in _BEAT_ENTRY_TASK_MAP.items():
            entry = app.conf.beat_schedule[entry_name]
            assert entry["task"] == task_name, (
                f"Beat entry '{entry_name}': expected task='{task_name}', got '{entry['task']}'"
            )

    def test_all_beat_entries_route_to_ml_training_queue(self) -> None:
        """Every retrain beat entry is routed to the ml_training queue."""
        app = _get_celery_app()
        for entry_name in _BEAT_ENTRY_TASK_MAP:
            entry = app.conf.beat_schedule[entry_name]
            options = entry.get("options", {})
            assert options.get("queue") == "ml_training", (
                f"Beat entry '{entry_name}' should have options.queue='ml_training'"
            )

    def test_task_routes_map_all_retrain_tasks_to_ml_training(self) -> None:
        """task_routes maps all five retrain tasks to the ml_training queue."""
        app = _get_celery_app()
        routes = app.conf.task_routes
        for name in _ALL_TASK_NAMES:
            assert name in routes, f"task_routes missing '{name}'"
            assert routes[name]["queue"] == "ml_training", (
                f"task_routes['{name}'] should route to ml_training"
            )


# ---------------------------------------------------------------------------
# Lazy-import guard — no top-level agent.strategies imports
# ---------------------------------------------------------------------------


class TestLazyImports:
    """agent.strategies must NOT be imported at the module level of retrain_tasks.py."""

    def test_no_top_level_agent_strategies_import(self) -> None:
        """retrain_tasks.py contains no top-level import of agent.strategies."""
        module_path = (
            Path(__file__).parent.parent.parent / "src" / "tasks" / "retrain_tasks.py"
        )
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        top_level_imports: list[str] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level_imports.append(node.module)

        for imp in top_level_imports:
            assert not imp.startswith("agent.strategies"), (
                f"Top-level import '{imp}' found — must be inside async function body"
            )


# ---------------------------------------------------------------------------
# Async bridge tests — _run_retraining_cycle_async
# ---------------------------------------------------------------------------


class TestRunRetrainingCycleAsync:
    """_run_retraining_cycle_async calls orchestrator.run_scheduled_cycle()."""

    async def test_calls_run_scheduled_cycle(self) -> None:
        """Bridge calls RetrainOrchestrator.run_scheduled_cycle()."""
        orc = _make_orchestrator()
        with _patch_retrain_module(orc):
            from src.tasks.retrain_tasks import _run_retraining_cycle_async  # noqa: PLC0415

            result = await _run_retraining_cycle_async()

        orc.run_scheduled_cycle.assert_called_once()
        assert isinstance(result, dict)

    async def test_returns_components_run_list(self) -> None:
        """Result contains a components_run list with the component name."""
        retrain_result = _make_retrain_result("ensemble", success=True, deployed=True)
        orc = _make_orchestrator(cycle_results=[retrain_result])
        with _patch_retrain_module(orc):
            from src.tasks.retrain_tasks import _run_retraining_cycle_async  # noqa: PLC0415

            result = await _run_retraining_cycle_async()

        assert result["components_run"] == ["ensemble"]
        assert result["total_run"] == 1

    async def test_deployed_component_in_components_deployed(self) -> None:
        """Deployed=True result appears in components_deployed."""
        retrain_result = _make_retrain_result("ensemble", success=True, deployed=True)
        orc = _make_orchestrator(cycle_results=[retrain_result])
        with _patch_retrain_module(orc):
            from src.tasks.retrain_tasks import _run_retraining_cycle_async  # noqa: PLC0415

            result = await _run_retraining_cycle_async()

        assert "ensemble" in result["components_deployed"]
        assert result["total_deployed"] == 1

    async def test_failed_component_in_components_failed(self) -> None:
        """success=False result appears in components_failed."""
        failed = _make_retrain_result("rl", success=False, deployed=False)
        orc = _make_orchestrator(cycle_results=[failed])
        with _patch_retrain_module(orc):
            from src.tasks.retrain_tasks import _run_retraining_cycle_async  # noqa: PLC0415

            result = await _run_retraining_cycle_async()

        assert "rl" in result["components_failed"]
        assert "rl" not in result["components_deployed"]

    async def test_exception_propagates(self) -> None:
        """If orchestrator.run_scheduled_cycle raises, the exception is not swallowed."""
        orc = MagicMock()
        orc.run_scheduled_cycle = AsyncMock(side_effect=RuntimeError("DB down"))
        with _patch_retrain_module(orc):
            from src.tasks.retrain_tasks import _run_retraining_cycle_async  # noqa: PLC0415

            with pytest.raises(RuntimeError, match="DB down"):
                await _run_retraining_cycle_async()


# ---------------------------------------------------------------------------
# Async bridge tests — individual component tasks
# ---------------------------------------------------------------------------


class TestIndividualAsyncBridges:
    """Each component _*_async function calls the correct orchestrator method."""

    async def test_retrain_ensemble_async_calls_correct_method(self) -> None:
        """_retrain_ensemble_async calls orchestrator.retrain_ensemble()."""
        orc = _make_orchestrator()
        with _patch_retrain_module(orc):
            from src.tasks.retrain_tasks import _retrain_ensemble_async  # noqa: PLC0415

            result = await _retrain_ensemble_async()

        orc.retrain_ensemble.assert_called_once()
        orc.retrain_regime.assert_not_called()
        orc.retrain_genome.assert_not_called()
        orc.retrain_rl.assert_not_called()
        assert result["component"] == "ensemble"

    async def test_retrain_regime_async_calls_correct_method(self) -> None:
        """_retrain_regime_async calls orchestrator.retrain_regime()."""
        orc = _make_orchestrator()
        with _patch_retrain_module(orc):
            from src.tasks.retrain_tasks import _retrain_regime_async  # noqa: PLC0415

            result = await _retrain_regime_async()

        orc.retrain_regime.assert_called_once()
        orc.retrain_ensemble.assert_not_called()
        assert result["component"] == "regime"

    async def test_retrain_genome_async_calls_correct_method(self) -> None:
        """_retrain_genome_async calls orchestrator.retrain_genome()."""
        orc = _make_orchestrator()
        with _patch_retrain_module(orc):
            from src.tasks.retrain_tasks import _retrain_genome_async  # noqa: PLC0415

            result = await _retrain_genome_async()

        orc.retrain_genome.assert_called_once()
        orc.retrain_ensemble.assert_not_called()
        assert result["component"] == "genome"

    async def test_retrain_rl_async_calls_correct_method(self) -> None:
        """_retrain_rl_async calls orchestrator.retrain_rl()."""
        orc = _make_orchestrator()
        with _patch_retrain_module(orc):
            from src.tasks.retrain_tasks import _retrain_rl_async  # noqa: PLC0415

            result = await _retrain_rl_async()

        orc.retrain_rl.assert_called_once()
        orc.retrain_ensemble.assert_not_called()
        assert result["component"] == "rl"

    async def test_return_value_includes_all_log_dict_keys(self) -> None:
        """Each async bridge returns to_log_dict() output including success/deployed."""
        orc = _make_orchestrator()
        tasks_and_components = [
            ("_retrain_ensemble_async", "ensemble"),
            ("_retrain_regime_async", "regime"),
            ("_retrain_genome_async", "genome"),
            ("_retrain_rl_async", "rl"),
        ]
        with _patch_retrain_module(orc):
            import src.tasks.retrain_tasks as rt  # noqa: PLC0415

            for fn_name, component in tasks_and_components:
                fn = getattr(rt, fn_name)
                result = await fn()
                assert "component" in result, f"{fn_name} missing 'component'"
                assert result["component"] == component
                assert "success" in result
                assert "deployed" in result

    async def test_ensemble_async_exception_propagates(self) -> None:
        """If orchestrator.retrain_ensemble raises, the exception propagates."""
        orc = MagicMock()
        orc.retrain_ensemble = AsyncMock(side_effect=ValueError("weights unavailable"))
        with _patch_retrain_module(orc):
            from src.tasks.retrain_tasks import _retrain_ensemble_async  # noqa: PLC0415

            with pytest.raises(ValueError, match="weights unavailable"):
                await _retrain_ensemble_async()

    async def test_rl_async_exception_propagates(self) -> None:
        """If orchestrator.retrain_rl raises, the exception propagates."""
        orc = MagicMock()
        orc.retrain_rl = AsyncMock(side_effect=RuntimeError("GPU OOM"))
        with _patch_retrain_module(orc):
            from src.tasks.retrain_tasks import _retrain_rl_async  # noqa: PLC0415

            with pytest.raises(RuntimeError, match="GPU OOM"):
                await _retrain_rl_async()


# ---------------------------------------------------------------------------
# duration_ms injection test (sync wrapper level)
# ---------------------------------------------------------------------------


class TestDurationMsInjection:
    """The sync Celery task wrappers inject duration_ms into the return dict."""

    def test_duration_ms_present_in_sync_wrapper(self) -> None:
        """Calling run_retraining_cycle() directly returns a dict with duration_ms."""
        orc = _make_orchestrator()

        async def _fake_cycle() -> dict[str, Any]:
            return {
                "components_run": ["ensemble"],
                "components_deployed": ["ensemble"],
                "components_failed": [],
                "total_run": 1,
                "total_deployed": 1,
                "results": [],
            }

        with _patch_retrain_module(orc):
            import src.tasks.retrain_tasks as rt  # noqa: PLC0415

            with patch.object(rt, "_run_retraining_cycle_async", new=_fake_cycle):
                result = rt.run_retraining_cycle()

        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0

    def test_duration_ms_present_in_retrain_ensemble_wrapper(self) -> None:
        """Calling retrain_ensemble() directly returns a dict with duration_ms."""
        orc = _make_orchestrator()

        async def _fake_ensemble() -> dict[str, Any]:
            return {"component": "ensemble", "success": True, "deployed": True}

        with _patch_retrain_module(orc):
            import src.tasks.retrain_tasks as rt  # noqa: PLC0415

            with patch.object(rt, "_retrain_ensemble_async", new=_fake_ensemble):
                result = rt.retrain_ensemble()

        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0
