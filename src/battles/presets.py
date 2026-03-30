"""Battle preset configurations.

Each preset provides default configuration values for common battle scenarios.
Developers can also create fully custom configurations.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class BattlePreset:
    """A preset battle configuration template.

    Attributes:
        key:              Machine-readable identifier.
        name:             Human-readable name.
        description:      Short description of the preset.
        duration_type:    ``"fixed"`` or ``"unlimited"``.
        duration_seconds: Duration in seconds (None for unlimited).
        starting_balance: Default starting balance in USDT.
        allowed_pairs:    List of allowed pairs (None = all).
        best_for:         Short description of ideal use case.
    """

    key: str
    name: str
    description: str
    duration_type: str
    duration_seconds: int | None
    starting_balance: Decimal
    allowed_pairs: list[str] | None
    best_for: str


BATTLE_PRESETS: dict[str, BattlePreset] = {
    "quick_1h": BattlePreset(
        key="quick_1h",
        name="Quick Sprint",
        description="1-hour fast-paced battle with top pairs.",
        duration_type="fixed",
        duration_seconds=3600,
        starting_balance=Decimal("10000"),
        allowed_pairs=None,
        best_for="Fast strategy comparison",
    ),
    "day_trader": BattlePreset(
        key="day_trader",
        name="Day Trader",
        description="24-hour full-day performance test.",
        duration_type="fixed",
        duration_seconds=86400,
        starting_balance=Decimal("10000"),
        allowed_pairs=None,
        best_for="Full-day performance test",
    ),
    "marathon": BattlePreset(
        key="marathon",
        name="Marathon",
        description="7-day endurance battle testing consistency.",
        duration_type="fixed",
        duration_seconds=604800,
        starting_balance=Decimal("10000"),
        allowed_pairs=None,
        best_for="Endurance and consistency",
    ),
    "scalper_duel": BattlePreset(
        key="scalper_duel",
        name="Scalper Duel",
        description="4-hour high-frequency battle on BTC + ETH only.",
        duration_type="fixed",
        duration_seconds=14400,
        starting_balance=Decimal("5000"),
        allowed_pairs=["BTCUSDT", "ETHUSDT"],
        best_for="High-frequency testing",
    ),
    "survival": BattlePreset(
        key="survival",
        name="Survival Mode",
        description="No time limit — last agent standing wins.",
        duration_type="unlimited",
        duration_seconds=None,
        starting_balance=Decimal("10000"),
        allowed_pairs=None,
        best_for="Last agent standing",
    ),
    "historical_day": BattlePreset(
        key="historical_day",
        name="Historical Day",
        description="1-day historical battle with 1-minute candles.",
        duration_type="historical",
        duration_seconds=86400,
        starting_balance=Decimal("10000"),
        allowed_pairs=None,
        best_for="Quick historical comparison",
    ),
    "historical_week": BattlePreset(
        key="historical_week",
        name="Historical Week",
        description="7-day historical battle with 5-minute candles.",
        duration_type="historical",
        duration_seconds=604800,
        starting_balance=Decimal("10000"),
        allowed_pairs=None,
        best_for="Week-long historical analysis",
    ),
    "historical_month": BattlePreset(
        key="historical_month",
        name="Historical Month",
        description="30-day historical battle with 1-hour candles.",
        duration_type="historical",
        duration_seconds=2592000,
        starting_balance=Decimal("10000"),
        allowed_pairs=None,
        best_for="Long-term historical strategy testing",
    ),
}


def get_preset(key: str) -> BattlePreset | None:
    """Return a preset by key, or None if not found."""
    return BATTLE_PRESETS.get(key)


def get_preset_config(key: str) -> dict[str, object]:
    """Return the config dict for a preset, suitable for Battle.config JSONB."""
    preset = BATTLE_PRESETS.get(key)
    if preset is None:
        return {}
    config: dict[str, object] = {
        "duration_type": preset.duration_type,
        "duration_seconds": preset.duration_seconds,
        "starting_balance": str(preset.starting_balance),
        "allowed_pairs": preset.allowed_pairs,
        "wallet_mode": "fresh",
    }
    if preset.duration_type == "historical":
        config["battle_mode"] = "historical"
        # Default candle intervals for historical presets
        candle_intervals = {
            "historical_day": 60,
            "historical_week": 300,
            "historical_month": 3600,
        }
        config["candle_interval"] = candle_intervals.get(key, 60)
    return config


def list_presets() -> list[dict[str, object]]:
    """Return all presets as serializable dicts."""
    return [
        {
            "key": p.key,
            "name": p.name,
            "description": p.description,
            "duration_type": p.duration_type,
            "duration_seconds": p.duration_seconds,
            "starting_balance": str(p.starting_balance),
            "allowed_pairs": p.allowed_pairs,
            "best_for": p.best_for,
        }
        for p in BATTLE_PRESETS.values()
    ]
