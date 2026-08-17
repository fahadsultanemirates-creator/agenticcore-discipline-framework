from __future__ import annotations

from datetime import datetime, timezone

import pytest

from discipline_framework.mt5_bridge.mock_client import DEFAULT_SYMBOL_INFO
from discipline_framework.rules.models import (
    CooldownRules,
    RiskRules,
    SessionRules,
    TargetRules,
    TradingRules,
)

NOW = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)  # 10:00 UTC, inside the default session


@pytest.fixture
def rules() -> TradingRules:
    return _default_rules()


@pytest.fixture
def symbol_info():
    return dict(DEFAULT_SYMBOL_INFO)


@pytest.fixture
def isolated_state_dirs(tmp_path, monkeypatch):
    """Redirects the module-level rules_overrides/state directories to a
    tmp_path so tests exercising RulesStore.load()/PausableEnforcer's
    file-backed pause via build_account_runtime() never write into the
    real project's config/rules_overrides/ or state/ directories."""
    import discipline_framework.config as config_module

    monkeypatch.setattr(config_module, "DEFAULT_RULES_OVERRIDES_DIR", tmp_path / "rules_overrides")
    monkeypatch.setattr(config_module, "DEFAULT_CONTROL_STATE_DIR", tmp_path / "state")
    return tmp_path


@pytest.fixture
def make_account_config(tmp_path):
    """Factory for a minimal, valid AccountConfig backed by a real
    (tmp_path) rules YAML file, so rules_path_for(account) resolves to
    something that actually exists on disk."""
    from discipline_framework.config import AccountConfig, AccountEnforcementConfig, AccountMT5Config

    def _make(account_id="account_1", rules=None, mode="passive", allow_live_execution=False):
        import yaml

        rules_obj = rules if rules is not None else _default_rules()
        rules_path = tmp_path / f"{account_id}_rules.yaml"
        with rules_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(rules_obj.model_dump(mode="json"), f)

        return AccountConfig(
            id=account_id,
            display_name=account_id.replace("_", " ").title(),
            enabled=True,
            rules_file=str(rules_path),
            mt5=AccountMT5Config(
                login_env=f"{account_id.upper()}_LOGIN",
                password_env=f"{account_id.upper()}_PASSWORD",
                server_env=f"{account_id.upper()}_SERVER",
            ),
            enforcement=AccountEnforcementConfig(mode=mode, allow_live_execution=allow_live_execution),
        )

    return _make


class RecordingInnerEnforcer:
    """A bare Enforcer stand-in that just records what it was asked to
    handle, for tests that care about wiring (did the right account's
    enforcer get called) rather than any specific enforcement mode's
    behavior — that's covered separately in test_enforcement.py."""

    def __init__(self, mode_name: str = "passive"):
        self.mode_name = mode_name
        self.alerter = object()
        self.calls = []

    def handle(self, results, bridge, snapshot):
        self.calls.append(results)


@pytest.fixture
def make_account_runtime(tmp_path, make_account_config):
    """Factory for a fully in-memory AccountRuntime (mock bridge, in-memory
    RulesStore/PausableEnforcer — no rules_overrides or state files
    involved) for tests of CommandHandlers/AccountWorker wiring that don't
    need real cross-process file coordination (that's covered separately in
    test_rules_store.py and test_pausable_enforcer.py)."""
    from discipline_framework.accounts import AccountRuntime
    from discipline_framework.enforcement.pausable import PausableEnforcer
    from discipline_framework.logging_stats.logger import ComplianceLogger
    from discipline_framework.mt5_bridge.mock_client import MockMT5Client
    from discipline_framework.rules.engine import RuleEngine
    from discipline_framework.rules.store import RulesStore

    def _make(account_id="account_1", rules=None, mode="passive", bridge=None):
        account = make_account_config(account_id=account_id, rules=rules, mode=mode)
        rules_store = RulesStore(rules if rules is not None else _default_rules())
        enforcer = PausableEnforcer(RecordingInnerEnforcer(mode_name=mode))
        return AccountRuntime(
            account=account,
            bridge=bridge if bridge is not None else MockMT5Client(),
            rules_store=rules_store,
            enforcer=enforcer,
            engine=RuleEngine(rules_store),
            compliance_logger=ComplianceLogger(tmp_path / f"{account_id}.jsonl"),
        )

    return _make


@pytest.fixture
def settings():
    from discipline_framework.config import Settings

    return Settings.model_validate(
        {
            "monitoring": {"poll_interval_seconds": 30, "history_lookback_days": 2},
            "mt5": {"force_mock": False},
            "telegram": {"enabled": False},
            "logging": {"log_dir": "logs", "compliance_log_dir": "compliance"},
        }
    )


def _default_rules() -> TradingRules:
    return TradingRules(
        risk=RiskRules(max_risk_per_trade_pct=2.0, max_daily_loss_pct=5.0, max_concurrent_positions=3),
        targets=TargetRules(
            require_stop_loss=True,
            default_stop_loss_pips=30,
            require_take_profit=True,
            default_take_profit_pips=60,
        ),
        cooldown=CooldownRules(
            consecutive_losses_trigger=2, cooldown_minutes=60, daily_loss_cooldown_minutes=1440
        ),
        session=SessionRules(
            allowed_symbols=["EURUSD", "GBPUSD", "USDJPY"],
            trading_start_utc="07:00",
            trading_end_utc="16:00",
            max_trades_per_day=5,
        ),
    )
