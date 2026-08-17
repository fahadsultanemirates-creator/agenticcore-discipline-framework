"""Sanity checks that the actual shipped config files parse and validate —
catches a typo in config/settings.yaml, config/accounts.yaml, or any
config/rules/*.yaml before it ever reaches a monitoring run."""

from discipline_framework.config import (
    DEFAULT_ACCOUNTS_PATH,
    DEFAULT_SETTINGS_PATH,
    load_accounts,
    load_settings,
    load_trading_rules,
    rules_overrides_path_for,
    rules_path_for,
)


def test_shipped_settings_yaml_is_valid():
    settings = load_settings(DEFAULT_SETTINGS_PATH)
    assert settings.telegram.commands_enabled is True
    # Not asserting a specific value here: an empty list means open/testing
    # access, a non-empty one means it's locked to specific Telegram user
    # IDs — both are valid states for this file depending on deployment
    # stage. Just check it's the right shape.
    assert isinstance(settings.telegram.authorized_user_ids, list)
    assert all(isinstance(uid, int) for uid in settings.telegram.authorized_user_ids)


def test_shipped_accounts_yaml_is_valid():
    accounts = load_accounts(DEFAULT_ACCOUNTS_PATH)
    assert {a.id for a in accounts} == {"account_1", "account_2"}
    assert all(a.enforcement.mode == "passive" for a in accounts)
    assert all(a.enforcement.allow_live_execution is False for a in accounts)


def test_each_shipped_account_rules_file_is_valid():
    for account in load_accounts(DEFAULT_ACCOUNTS_PATH):
        rules = load_trading_rules(rules_path_for(account))
        assert rules.risk.max_risk_per_trade_pct > 0
        assert rules.session.allowed_symbols


def test_accounts_have_distinct_risk_settings():
    """account_2 is deliberately shipped more conservative than account_1 —
    guards against someone "simplifying" the placeholders back to identical
    files and silently losing the multi-account demonstration."""
    accounts = {a.id: a for a in load_accounts(DEFAULT_ACCOUNTS_PATH)}
    rules_1 = load_trading_rules(rules_path_for(accounts["account_1"]))
    rules_2 = load_trading_rules(rules_path_for(accounts["account_2"]))
    assert rules_1.risk.max_risk_per_trade_pct != rules_2.risk.max_risk_per_trade_pct


def test_accounts_have_distinct_override_paths():
    accounts = {a.id: a for a in load_accounts(DEFAULT_ACCOUNTS_PATH)}
    path_1 = rules_overrides_path_for(accounts["account_1"])
    path_2 = rules_overrides_path_for(accounts["account_2"])
    assert path_1 != path_2
