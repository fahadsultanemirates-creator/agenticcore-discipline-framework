from __future__ import annotations

from discipline_framework.commands.handlers import CommandHandlers


def make_handlers(make_account_runtime, rules, account_ids=("account_1", "account_2")):
    runtimes = {aid: make_account_runtime(account_id=aid, rules=rules) for aid in account_ids}
    return CommandHandlers(runtimes), runtimes


def test_setrisk_updates_only_the_named_account(make_account_runtime, rules):
    handlers, runtimes = make_handlers(make_account_runtime, rules)
    reply = handlers.dispatch("setrisk", ["account_1", "1.5"])
    assert "1.5%" in reply
    assert runtimes["account_1"].rules_store.rules.risk.max_risk_per_trade_pct == 1.5
    assert runtimes["account_2"].rules_store.rules.risk.max_risk_per_trade_pct == rules.risk.max_risk_per_trade_pct


def test_setrisk_unknown_account_lists_known_accounts(make_account_runtime, rules):
    handlers, _ = make_handlers(make_account_runtime, rules)
    reply = handlers.dispatch("setrisk", ["not_an_account", "1.5"])
    assert reply.startswith("⚠️")
    assert "account_1" in reply and "account_2" in reply


def test_setrisk_missing_account_arg_is_usage_error(make_account_runtime, rules):
    handlers, _ = make_handlers(make_account_runtime, rules)
    reply = handlers.dispatch("setrisk", ["1.5"])  # no account id
    assert reply.startswith("⚠️")
    assert "usage" in reply


def test_setrisk_accepts_percent_sign(make_account_runtime, rules):
    handlers, runtimes = make_handlers(make_account_runtime, rules)
    handlers.dispatch("setrisk", ["account_1", "2%"])
    assert runtimes["account_1"].rules_store.rules.risk.max_risk_per_trade_pct == 2.0


def test_setrisk_out_of_range_returns_validation_error(make_account_runtime, rules):
    handlers, runtimes = make_handlers(make_account_runtime, rules)
    reply = handlers.dispatch("setrisk", ["account_1", "500"])
    assert reply.startswith("⚠️")
    assert runtimes["account_1"].rules_store.rules.risk.max_risk_per_trade_pct == rules.risk.max_risk_per_trade_pct


def test_setdailyloss(make_account_runtime, rules):
    handlers, runtimes = make_handlers(make_account_runtime, rules)
    handlers.dispatch("setdailyloss", ["account_2", "3"])
    assert runtimes["account_2"].rules_store.rules.risk.max_daily_loss_pct == 3.0
    assert runtimes["account_1"].rules_store.rules.risk.max_daily_loss_pct == rules.risk.max_daily_loss_pct


def test_setcooldown(make_account_runtime, rules):
    handlers, runtimes = make_handlers(make_account_runtime, rules)
    reply = handlers.dispatch("setcooldown", ["account_1", "3", "90"])
    assert runtimes["account_1"].rules_store.rules.cooldown.consecutive_losses_trigger == 3
    assert runtimes["account_1"].rules_store.rules.cooldown.cooldown_minutes == 90
    assert "account_1" in reply


def test_setcooldown_wrong_arity(make_account_runtime, rules):
    handlers, _ = make_handlers(make_account_runtime, rules)
    reply = handlers.dispatch("setcooldown", ["account_1", "3"])
    assert reply.startswith("⚠️")


def test_setpairs_parses_comma_list(make_account_runtime, rules):
    handlers, runtimes = make_handlers(make_account_runtime, rules)
    reply = handlers.dispatch("setpairs", ["account_1", "eurusd,gbpjpy", ",", "usdchf"])
    assert runtimes["account_1"].rules_store.rules.session.allowed_symbols == ["EURUSD", "GBPJPY", "USDCHF"]
    assert "EURUSD" in reply


def test_setsession_explicit_range(make_account_runtime, rules):
    handlers, runtimes = make_handlers(make_account_runtime, rules)
    handlers.dispatch("setsession", ["account_1", "08:00-17:00"])
    assert runtimes["account_1"].rules_store.rules.session.trading_start_utc == "08:00"
    assert runtimes["account_1"].rules_store.rules.session.trading_end_utc == "17:00"


def test_setsession_named_preset(make_account_runtime, rules):
    handlers, runtimes = make_handlers(make_account_runtime, rules)
    handlers.dispatch("setsession", ["account_1", "london"])
    assert runtimes["account_1"].rules_store.rules.session.trading_start_utc == "07:00"


def test_setsession_unknown_name_is_rejected(make_account_runtime, rules):
    handlers, _ = make_handlers(make_account_runtime, rules)
    reply = handlers.dispatch("setsession", ["account_1", "mars"])
    assert reply.startswith("⚠️")


def test_setmaxtrades(make_account_runtime, rules):
    handlers, runtimes = make_handlers(make_account_runtime, rules)
    handlers.dispatch("setmaxtrades", ["account_1", "8"])
    assert runtimes["account_1"].rules_store.rules.session.max_trades_per_day == 8


def test_status_single_account(make_account_runtime, rules):
    handlers, _ = make_handlers(make_account_runtime, rules)
    handlers.dispatch("setrisk", ["account_1", "1.5"])
    reply = handlers.dispatch("status", ["account_1"])
    assert "account_1" in reply
    assert "1.5%" in reply
    assert "account_2" not in reply


def test_status_all_includes_every_account(make_account_runtime, rules):
    handlers, _ = make_handlers(make_account_runtime, rules)
    reply = handlers.dispatch("status", ["all"])
    assert "account_1" in reply
    assert "account_2" in reply


def test_pause_single_account_does_not_affect_others(make_account_runtime, rules):
    handlers, runtimes = make_handlers(make_account_runtime, rules)
    handlers.dispatch("pause", ["account_1"])
    assert runtimes["account_1"].enforcer.enabled is False
    assert runtimes["account_2"].enforcer.enabled is True


def test_pause_all_pauses_every_account(make_account_runtime, rules):
    handlers, runtimes = make_handlers(make_account_runtime, rules)
    handlers.dispatch("pause", ["all"])
    assert all(not r.enforcer.enabled for r in runtimes.values())

    handlers.dispatch("resume", ["all"])
    assert all(r.enforcer.enabled for r in runtimes.values())


def test_accounts_command_lists_every_running_account(make_account_runtime, rules):
    handlers, _ = make_handlers(make_account_runtime, rules)
    reply = handlers.dispatch("accounts", [])
    assert "account_1" in reply
    assert "account_2" in reply


def test_accounts_command_with_no_accounts():
    handlers = CommandHandlers({})
    reply = handlers.dispatch("accounts", [])
    assert "No accounts" in reply


def test_unknown_command(make_account_runtime, rules):
    handlers, _ = make_handlers(make_account_runtime, rules)
    reply = handlers.dispatch("nonsense", [])
    assert "Unknown command" in reply


def test_help_mentions_account_id(make_account_runtime, rules):
    handlers, _ = make_handlers(make_account_runtime, rules)
    reply = handlers.dispatch("help", [])
    assert "account_id" in reply
    assert "/accounts" in reply
