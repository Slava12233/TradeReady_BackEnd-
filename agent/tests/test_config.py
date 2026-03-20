"""Tests for agent/config.py :: AgentConfig."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.config import AgentConfig


class TestAgentConfig:
    """Tests for AgentConfig pydantic-settings class."""

    def test_loads_required_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AgentConfig reads openrouter_api_key from the environment."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-abc123")
        # Isolate from any real .env file by providing all required env vars
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        assert config.openrouter_api_key == "sk-test-abc123"

    def test_missing_openrouter_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Constructing AgentConfig without openrouter_api_key raises ValidationError."""
        # Remove the key from the environment to guarantee it is absent
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(ValidationError, match="openrouter_api_key"):
            AgentConfig(_env_file=None)  # type: ignore[call-arg]

    def test_default_agent_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """agent_model defaults to the Claude Sonnet 4-5 openrouter string."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        assert config.agent_model == "openrouter:anthropic/claude-sonnet-4-5"

    def test_default_cheap_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """agent_cheap_model defaults to Gemini 2.0 Flash."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        assert config.agent_cheap_model == "openrouter:google/gemini-2.0-flash-001"

    def test_default_platform_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """platform_base_url defaults to localhost:8000."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        assert config.platform_base_url == "http://localhost:8000"

    def test_default_platform_api_key_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """platform_api_key defaults to an empty string."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        assert config.platform_api_key == ""

    def test_default_max_trade_pct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """max_trade_pct defaults to 0.05 (5%)."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        assert config.max_trade_pct == 0.05

    def test_default_symbols(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """symbols defaults to BTCUSDT, ETHUSDT, SOLUSDT."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        assert config.symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    def test_overrides_via_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables override defaults for all settable fields."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-custom-key")
        monkeypatch.setenv("PLATFORM_BASE_URL", "http://prod.example.com:8000")
        monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_testkey")
        monkeypatch.setenv("MAX_TRADE_PCT", "0.02")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        assert config.openrouter_api_key == "sk-custom-key"
        assert config.platform_base_url == "http://prod.example.com:8000"
        assert config.platform_api_key == "ak_live_testkey"
        assert config.max_trade_pct == 0.02

    def test_platform_root_computed_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """platform_root returns the project root (parent of the agent/ directory)."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        root = config.platform_root
        assert isinstance(root, Path)
        assert root.is_absolute()
        # The root must be the parent of agent/config.py's parent directory
        assert (root / "agent").exists() or root.name != "agent"
        # Ensure platform_root is NOT the agent/ directory itself
        from agent.config import _ENV_FILE
        agent_dir = _ENV_FILE.parent
        assert root == agent_dir.parent.resolve()

    def test_platform_root_contains_agent_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The project root computed by platform_root contains the agent/ subdirectory."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        assert (config.platform_root / "agent").is_dir()

    def test_case_insensitive_env_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """pydantic-settings is configured case-insensitive; lowercase env works too."""
        monkeypatch.setenv("openrouter_api_key", "sk-lower")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        assert config.openrouter_api_key == "sk-lower"

    def test_extra_env_vars_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """extra='ignore' means unknown env vars do not raise an error."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("COMPLETELY_UNKNOWN_VAR", "should_be_ignored")
        # Should not raise
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        assert not hasattr(config, "completely_unknown_var")
