from __future__ import annotations

from datetime import timedelta

from discipline_framework.mt5_bridge.models import AccountSnapshot, Position, Trade, TradeDirection
from discipline_framework.rules.engine import RuleEngine
from tests.conftest import NOW


def make_position(**overrides) -> Position:
    defaults = dict(
        ticket=1,
        symbol="EURUSD",
        direction=TradeDirection.BUY,
        volume=0.1,
        open_price=1.1000,
        open_time=NOW,
        stop_loss=1.0990,  # 10 pips — small, compliant risk by default
        take_profit=1.1050,
        current_price=1.1010,
        profit=10.0,
    )
    defaults.update(overrides)
    return Position(**defaults)


def make_trade(**overrides) -> Trade:
    defaults = dict(
        ticket=1,
        symbol="EURUSD",
        direction=TradeDirection.BUY,
        volume=0.1,
        open_time=NOW - timedelta(hours=1),
        close_time=NOW - timedelta(minutes=30),
        profit=-50.0,
    )
    defaults.update(overrides)
    return Trade(**defaults)


def make_snapshot(**overrides) -> AccountSnapshot:
    from discipline_framework.mt5_bridge.mock_client import DEFAULT_SYMBOL_INFO

    defaults = dict(
        as_of=NOW,
        balance=10_000.0,
        equity=10_000.0,
        open_positions=[],
        closed_trades_today=[],
        symbol_info=dict(DEFAULT_SYMBOL_INFO),
    )
    defaults.update(overrides)
    return AccountSnapshot(**defaults)


def failed_rule_ids(results) -> set[str]:
    return {r.rule_id for r in results if not r.passed}


def test_fully_compliant_snapshot_has_no_violations(rules):
    engine = RuleEngine(rules)
    snapshot = make_snapshot(open_positions=[make_position()])
    results = engine.evaluate(snapshot)
    assert failed_rule_ids(results) == set()
    assert all(r.passed for r in results)


def test_missing_stop_loss_is_flagged(rules):
    engine = RuleEngine(rules)
    snapshot = make_snapshot(open_positions=[make_position(stop_loss=None)])
    results = engine.evaluate(snapshot)
    assert "stop_loss_required" in failed_rule_ids(results)


def test_missing_take_profit_is_flagged(rules):
    engine = RuleEngine(rules)
    snapshot = make_snapshot(open_positions=[make_position(take_profit=None)])
    results = engine.evaluate(snapshot)
    assert "take_profit_required" in failed_rule_ids(results)


def test_oversized_risk_is_flagged(rules):
    engine = RuleEngine(rules)
    # 50-pip stop on a 1.0 lot EURUSD position against $10k equity: 5% risk, well above the 2% cap.
    snapshot = make_snapshot(
        open_positions=[make_position(volume=1.0, open_price=1.1000, stop_loss=1.0950)]
    )
    results = engine.evaluate(snapshot)
    assert "max_risk_per_trade" in failed_rule_ids(results)


def test_disallowed_symbol_is_flagged(rules):
    engine = RuleEngine(rules)
    snapshot = make_snapshot(open_positions=[make_position(symbol="XAUUSD")])
    results = engine.evaluate(snapshot)
    assert "allowed_symbol" in failed_rule_ids(results)


def test_outside_trading_session_is_flagged(rules):
    engine = RuleEngine(rules)
    late_night = NOW.replace(hour=2, minute=0)  # outside the 07:00-16:00 UTC session
    snapshot = make_snapshot(open_positions=[make_position(open_time=late_night)])
    results = engine.evaluate(snapshot)
    assert "trading_session" in failed_rule_ids(results)


def test_max_concurrent_positions_is_flagged(rules):
    engine = RuleEngine(rules)
    positions = [make_position(ticket=i) for i in range(1, 6)]  # 5 > limit of 3
    snapshot = make_snapshot(open_positions=positions)
    results = engine.evaluate(snapshot)
    assert "max_concurrent_positions" in failed_rule_ids(results)


def test_max_trades_per_day_is_flagged(rules):
    engine = RuleEngine(rules)
    closed = [make_trade(ticket=i, profit=10.0) for i in range(1, 7)]  # 6 > limit of 5
    snapshot = make_snapshot(closed_trades_today=closed)
    results = engine.evaluate(snapshot)
    assert "max_trades_per_day" in failed_rule_ids(results)


def test_consecutive_loss_cooldown_blocks_new_trade(rules):
    engine = RuleEngine(rules)
    losses = [
        make_trade(ticket=1, profit=-50.0, close_time=NOW - timedelta(minutes=40)),
        make_trade(ticket=2, profit=-30.0, close_time=NOW - timedelta(minutes=20)),
    ]
    # Opened after the second loss, while still inside the 60-minute cooldown.
    new_position = make_position(ticket=3, open_time=NOW - timedelta(minutes=5))
    snapshot = make_snapshot(closed_trades_today=losses, open_positions=[new_position])
    results = engine.evaluate(snapshot)
    assert "consecutive_loss_cooldown" in failed_rule_ids(results)


def test_consecutive_loss_cooldown_passes_when_no_new_trade_opened(rules):
    engine = RuleEngine(rules)
    losses = [
        make_trade(ticket=1, profit=-50.0, close_time=NOW - timedelta(minutes=40)),
        make_trade(ticket=2, profit=-30.0, close_time=NOW - timedelta(minutes=20)),
    ]
    snapshot = make_snapshot(closed_trades_today=losses, open_positions=[])
    results = engine.evaluate(snapshot)
    cooldown_results = [r for r in results if r.rule_id == "consecutive_loss_cooldown"]
    assert cooldown_results and all(r.passed for r in cooldown_results)


def test_consecutive_loss_cooldown_expires(rules):
    engine = RuleEngine(rules)
    losses = [
        make_trade(ticket=1, profit=-50.0, close_time=NOW - timedelta(minutes=200)),
        make_trade(ticket=2, profit=-30.0, close_time=NOW - timedelta(minutes=120)),  # cooldown ended 60 min ago
    ]
    new_position = make_position(ticket=3, open_time=NOW - timedelta(minutes=5))
    snapshot = make_snapshot(closed_trades_today=losses, open_positions=[new_position])
    results = engine.evaluate(snapshot)
    assert "consecutive_loss_cooldown" not in failed_rule_ids(results)


def test_max_daily_loss_breach_is_flagged(rules):
    engine = RuleEngine(rules)
    # $600 lost against $10k balance = 6%, above the 5% cap.
    losses = [make_trade(ticket=1, profit=-600.0)]
    snapshot = make_snapshot(balance=10_000.0, closed_trades_today=losses, open_positions=[])
    results = engine.evaluate(snapshot)
    assert "max_daily_loss" in failed_rule_ids(results)


def test_daily_loss_within_limit_passes(rules):
    engine = RuleEngine(rules)
    losses = [make_trade(ticket=1, profit=-100.0)]  # 1%, within the 5% cap
    snapshot = make_snapshot(balance=10_000.0, closed_trades_today=losses, open_positions=[])
    results = engine.evaluate(snapshot)
    assert "max_daily_loss" not in failed_rule_ids(results)
