"""RulesStore: the single mutable source of truth for TradingRules at
runtime, shared between the monitoring loop (reads) and the Telegram
command interface (writes).

Design: config/rules.yaml stays the hand-edited, heavily-commented
baseline. Telegram-driven changes are never written back into it — they're
tracked separately as a sparse "overrides" patch (only the fields actually
changed via chat), persisted to config/rules_overrides.yaml. On load, the
overrides are deep-merged on top of the baseline. That means:

- A dev can keep editing/re-deploying config/rules.yaml without a stray
  Telegram override silently reverting or masking unrelated fields.
- The overrides file is a plain, readable audit trail of exactly what was
  changed live and to what — not a full rules dump.
- Every write is validated (via TradingRules) *before* being committed or
  persisted, so a bad value from a command never corrupts live state.

Thread-safety: reads/writes are guarded by a lock, since the monitoring
loop and the Telegram polling thread both touch this concurrently. `.rules`
always returns a fully-formed, already-validated TradingRules snapshot —
never a partially-applied one.
"""

from __future__ import annotations

import threading
from pathlib import Path

import yaml

from discipline_framework.rules.models import TradingRules


class RulesStore:
    def __init__(self, rules: TradingRules, overrides_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._base_data = rules.model_dump(mode="json")
        self._overrides: dict = {}
        self._overrides_path = overrides_path
        self._rules = rules

    @classmethod
    def load(cls, base_rules_path: Path, overrides_path: Path | None = None) -> "RulesStore":
        base_rules = TradingRules.model_validate(_load_yaml(base_rules_path))
        store = cls(base_rules, overrides_path=overrides_path)

        if overrides_path and overrides_path.exists():
            overrides = _load_yaml(overrides_path)
            if overrides:
                merged = _deep_merge(store._base_data, overrides)
                store._rules = TradingRules.model_validate(merged)
                store._overrides = overrides
        return store

    @property
    def rules(self) -> TradingRules:
        with self._lock:
            return self._rules

    @property
    def overrides(self) -> dict:
        """The sparse set of fields currently overridden via Telegram (or a
        prior run's persisted overrides). Empty means rules.yaml as-is."""
        with self._lock:
            return dict(self._overrides)

    def set_max_risk_per_trade_pct(self, value: float) -> TradingRules:
        return self._apply_override({"risk": {"max_risk_per_trade_pct": value}})

    def set_max_daily_loss_pct(self, value: float) -> TradingRules:
        return self._apply_override({"risk": {"max_daily_loss_pct": value}})

    def set_cooldown(self, consecutive_losses_trigger: int, cooldown_minutes: int) -> TradingRules:
        return self._apply_override(
            {
                "cooldown": {
                    "consecutive_losses_trigger": consecutive_losses_trigger,
                    "cooldown_minutes": cooldown_minutes,
                }
            }
        )

    def set_allowed_symbols(self, symbols: list[str]) -> TradingRules:
        return self._apply_override({"session": {"allowed_symbols": symbols}})

    def set_session(self, trading_start_utc: str, trading_end_utc: str) -> TradingRules:
        return self._apply_override(
            {"session": {"trading_start_utc": trading_start_utc, "trading_end_utc": trading_end_utc}}
        )

    def set_max_trades_per_day(self, value: int) -> TradingRules:
        return self._apply_override({"session": {"max_trades_per_day": value}})

    def _apply_override(self, patch: dict) -> TradingRules:
        with self._lock:
            new_overrides = _deep_merge(self._overrides, patch)
            merged = _deep_merge(self._base_data, new_overrides)
            # Validates before anything is committed — an invalid value
            # raises pydantic.ValidationError here and self._rules/_overrides
            # are left untouched.
            new_rules = TradingRules.model_validate(merged)
            self._overrides = new_overrides
            self._rules = new_rules
            self._persist()
            return new_rules

    def _persist(self) -> None:
        if not self._overrides_path:
            return
        self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._overrides_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(self._overrides, f, sort_keys=False)
        tmp_path.replace(self._overrides_path)  # atomic on POSIX


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, overrides: dict) -> dict:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
