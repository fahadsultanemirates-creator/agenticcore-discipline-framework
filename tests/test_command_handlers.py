from __future__ import annotations

from discipline_framework.commands.handlers import CommandHandlers
from discipline_framework.enforcement.pausable import PausableEnforcer
from discipline_framework.rules.store import RulesStore


class RecordingEnforcer:
    mode_name = "passive"

    def __init__(self):
        self.alerter = object()

    def handle(self, results, bridge, snapshot):
        pass


def make_handlers(rules):
    store = RulesStore(rules)
    enforcer = PausableEnforcer(RecordingEnforcer())
    return CommandHandlers(store, enforcer), store, enforcer


def test_setrisk_updates_store(rules):
    handlers, store, _ = make_handlers(rules)
    reply = handlers.dispatch("setrisk", ["1.5"])
    assert "1.5%" in reply
    assert store.rules.risk.max_risk_per_trade_pct == 1.5


def test_setrisk_bad_input_returns_usage(rules):
    handlers, store, _ = make_handlers(rules)
    reply = handlers.dispatch("setrisk", ["notanumber"])
    assert reply.startswith("⚠️")
    assert "usage" in reply
    assert store.rules.risk.max_risk_per_trade_pct == rules.risk.max_risk_per_trade_pct


def test_setrisk_out_of_range_returns_validation_error(rules):
    handlers, store, _ = make_handlers(rules)
    reply = handlers.dispatch("setrisk", ["500"])
    assert reply.startswith("⚠️")
    assert store.rules.risk.max_risk_per_trade_pct == rules.risk.max_risk_per_trade_pct


def test_setdailyloss(rules):
    handlers, store, _ = make_handlers(rules)
    handlers.dispatch("setdailyloss", ["3"])
    assert store.rules.risk.max_daily_loss_pct == 3.0


def test_setcooldown(rules):
    handlers, store, _ = make_handlers(rules)
    reply = handlers.dispatch("setcooldown", ["3", "90"])
    assert store.rules.cooldown.consecutive_losses_trigger == 3
    assert store.rules.cooldown.cooldown_minutes == 90
    assert "3 consecutive losses" in reply


def test_setcooldown_wrong_arity(rules):
    handlers, store, _ = make_handlers(rules)
    reply = handlers.dispatch("setcooldown", ["3"])
    assert reply.startswith("⚠️")


def test_setpairs_parses_comma_list(rules):
    handlers, store, _ = make_handlers(rules)
    reply = handlers.dispatch("setpairs", ["eurusd,gbpjpy , usdchf"])
    assert store.rules.session.allowed_symbols == ["EURUSD", "GBPJPY", "USDCHF"]
    assert "EURUSD" in reply


def test_setsession_explicit_range(rules):
    handlers, store, _ = make_handlers(rules)
    handlers.dispatch("setsession", ["08:00-17:00"])
    assert store.rules.session.trading_start_utc == "08:00"
    assert store.rules.session.trading_end_utc == "17:00"


def test_setsession_named_preset(rules):
    handlers, store, _ = make_handlers(rules)
    handlers.dispatch("setsession", ["london"])
    assert store.rules.session.trading_start_utc == "07:00"
    assert store.rules.session.trading_end_utc == "16:00"


def test_setsession_unknown_name_is_rejected(rules):
    handlers, store, _ = make_handlers(rules)
    reply = handlers.dispatch("setsession", ["mars"])
    assert reply.startswith("⚠️")


def test_setmaxtrades(rules):
    handlers, store, _ = make_handlers(rules)
    handlers.dispatch("setmaxtrades", ["8"])
    assert store.rules.session.max_trades_per_day == 8


def test_status_reports_current_rules_and_state(rules):
    handlers, store, enforcer = make_handlers(rules)
    handlers.dispatch("setrisk", ["1.5"])
    reply = handlers.dispatch("status", [])
    assert "1.5%" in reply
    assert "ACTIVE" in reply


def test_pause_and_resume_flip_enforcer_state(rules):
    handlers, store, enforcer = make_handlers(rules)
    handlers.dispatch("pause", [])
    assert enforcer.enabled is False
    status = handlers.dispatch("status", [])
    assert "PAUSED" in status

    handlers.dispatch("resume", [])
    assert enforcer.enabled is True


def test_unknown_command(rules):
    handlers, *_ = make_handlers(rules)
    reply = handlers.dispatch("nonsense", [])
    assert "Unknown command" in reply


def test_help(rules):
    handlers, *_ = make_handlers(rules)
    reply = handlers.dispatch("help", [])
    assert "/setrisk" in reply
    assert "/pause" in reply
