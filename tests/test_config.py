"""Sanity checks that the actual shipped config files parse and validate —
catches a typo in config/rules.yaml or config/settings.yaml before it ever
reaches a monitoring run."""

from discipline_framework.config import DEFAULT_RULES_PATH, DEFAULT_SETTINGS_PATH, load_settings, load_trading_rules


def test_shipped_rules_yaml_is_valid():
    rules = load_trading_rules(DEFAULT_RULES_PATH)
    assert rules.risk.max_risk_per_trade_pct > 0
    assert "EURUSD" in rules.session.allowed_symbols


def test_shipped_settings_yaml_is_valid():
    settings = load_settings(DEFAULT_SETTINGS_PATH)
    assert settings.enforcement.mode == "passive"
    assert settings.enforcement.allow_live_execution is False
