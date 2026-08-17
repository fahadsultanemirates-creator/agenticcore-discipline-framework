from __future__ import annotations

import pytest
from pydantic import ValidationError

from discipline_framework.rules.store import RulesStore


def test_setter_updates_live_rules(rules):
    store = RulesStore(rules)
    updated = store.set_max_risk_per_trade_pct(1.25)
    assert updated.risk.max_risk_per_trade_pct == 1.25
    assert store.rules.risk.max_risk_per_trade_pct == 1.25


def test_invalid_value_is_rejected_and_state_is_untouched(rules):
    store = RulesStore(rules)
    with pytest.raises(ValidationError):
        store.set_max_risk_per_trade_pct(500)  # over the 100% ceiling
    assert store.rules.risk.max_risk_per_trade_pct == rules.risk.max_risk_per_trade_pct
    assert store.overrides == {}


def test_unrelated_fields_are_unaffected_by_a_setter(rules):
    store = RulesStore(rules)
    store.set_max_risk_per_trade_pct(1.0)
    assert store.rules.session.allowed_symbols == rules.session.allowed_symbols
    assert store.rules.cooldown.cooldown_minutes == rules.cooldown.cooldown_minutes


def test_persists_and_reloads_overrides(tmp_path, rules):
    base_path = tmp_path / "rules.yaml"
    overrides_path = tmp_path / "rules_overrides.yaml"
    import yaml

    with base_path.open("w") as f:
        yaml.safe_dump(rules.model_dump(mode="json"), f)

    store = RulesStore.load(base_path, overrides_path=overrides_path)
    store.set_max_risk_per_trade_pct(1.5)
    store.set_allowed_symbols(["EURUSD"])
    assert overrides_path.exists()

    reloaded = RulesStore.load(base_path, overrides_path=overrides_path)
    assert reloaded.rules.risk.max_risk_per_trade_pct == 1.5
    assert reloaded.rules.session.allowed_symbols == ["EURUSD"]
    # Untouched fields still come from the baseline file.
    assert reloaded.rules.cooldown.cooldown_minutes == rules.cooldown.cooldown_minutes


def test_editing_baseline_after_override_keeps_other_fields_live(tmp_path, rules):
    """An override on one field shouldn't freeze the whole rules file — a
    dev editing an untouched field in rules.yaml should still take effect."""
    import yaml

    base_path = tmp_path / "rules.yaml"
    overrides_path = tmp_path / "rules_overrides.yaml"
    with base_path.open("w") as f:
        yaml.safe_dump(rules.model_dump(mode="json"), f)

    store = RulesStore.load(base_path, overrides_path=overrides_path)
    store.set_max_risk_per_trade_pct(1.5)  # only risk.max_risk_per_trade_pct is overridden

    # Simulate a dev editing the baseline's max_trades_per_day afterward.
    data = rules.model_dump(mode="json")
    data["session"]["max_trades_per_day"] = 10
    with base_path.open("w") as f:
        yaml.safe_dump(data, f)

    reloaded = RulesStore.load(base_path, overrides_path=overrides_path)
    assert reloaded.rules.risk.max_risk_per_trade_pct == 1.5  # override still applies
    assert reloaded.rules.session.max_trades_per_day == 10  # baseline edit still takes effect


def test_reload_if_stale_noop_without_a_backing_file(rules):
    store = RulesStore(rules)  # no base_rules_path
    assert store.reload_if_stale() is False


def test_reload_if_stale_noop_when_nothing_changed(tmp_path, rules):
    import yaml

    base_path = tmp_path / "rules.yaml"
    with base_path.open("w") as f:
        yaml.safe_dump(rules.model_dump(mode="json"), f)

    store = RulesStore.load(base_path)
    assert store.reload_if_stale() is False


def test_reload_if_stale_picks_up_a_second_stores_override(tmp_path, rules):
    """The mechanism that lets a Telegram bot process and an account
    worker process coordinate through nothing but the filesystem."""
    import yaml

    base_path = tmp_path / "rules.yaml"
    overrides_path = tmp_path / "rules_overrides.yaml"
    with base_path.open("w") as f:
        yaml.safe_dump(rules.model_dump(mode="json"), f)

    worker_side = RulesStore.load(base_path, overrides_path=overrides_path)
    bot_side = RulesStore.load(base_path, overrides_path=overrides_path)

    bot_side.set_max_risk_per_trade_pct(1.25)
    assert worker_side.rules.risk.max_risk_per_trade_pct != 1.25  # not yet reloaded

    assert worker_side.reload_if_stale() is True
    assert worker_side.rules.risk.max_risk_per_trade_pct == 1.25
    assert worker_side.reload_if_stale() is False  # already up to date


def test_setters_for_all_command_backed_fields(rules):
    store = RulesStore(rules)
    updated = store.set_max_daily_loss_pct(3.0)
    assert updated.risk.max_daily_loss_pct == 3.0

    updated = store.set_cooldown(3, 90)
    assert updated.cooldown.consecutive_losses_trigger == 3
    assert updated.cooldown.cooldown_minutes == 90

    updated = store.set_session("08:00", "17:00")
    assert updated.session.trading_start_utc == "08:00"
    assert updated.session.trading_end_utc == "17:00"

    updated = store.set_max_trades_per_day(8)
    assert updated.session.max_trades_per_day == 8
