from __future__ import annotations

import os

import pytest

from discipline_framework.enforcement.active import ActiveEnforcer
from discipline_framework.enforcement.base import LIVE_CONFIRM_ENV_VAR, LiveExecutionNotConfirmed
from discipline_framework.enforcement.hybrid import HybridEnforcer
from discipline_framework.enforcement.passive import PassiveEnforcer
from discipline_framework.mt5_bridge.mock_client import MockMT5Client
from discipline_framework.mt5_bridge.models import Position, TradeDirection
from discipline_framework.rules.models import CheckResult, Severity
from tests.conftest import NOW
from tests.test_rule_engine import make_snapshot


class RecordingAlerter:
    def __init__(self):
        self.sent = []

    def send_violation(self, result, mode):
        self.sent.append((result, mode))
        return True


def failed(rule_id, **context):
    return CheckResult(
        rule_id=rule_id, passed=False, severity=Severity.CRITICAL, message="test violation", context=context
    )


def passed(rule_id):
    return CheckResult(rule_id=rule_id, passed=True, severity=Severity.INFO, message="ok")


def test_passive_enforcer_alerts_on_violations_only():
    alerter = RecordingAlerter()
    enforcer = PassiveEnforcer(alerter)
    results = [failed("stop_loss_required"), passed("allowed_symbol")]
    bridge = MockMT5Client()
    enforcer.handle(results, bridge, make_snapshot())
    assert len(alerter.sent) == 1
    assert alerter.sent[0][0].rule_id == "stop_loss_required"


def test_passive_enforcer_never_touches_the_bridge():
    alerter = RecordingAlerter()
    enforcer = PassiveEnforcer(alerter)
    bridge = MockMT5Client(
        open_positions=[
            Position(
                ticket=1,
                symbol="EURUSD",
                direction=TradeDirection.BUY,
                volume=0.1,
                open_price=1.1,
                open_time=NOW,
                stop_loss=None,
                take_profit=None,
                current_price=1.1,
                profit=0.0,
            )
        ]
    )
    enforcer.handle([failed("max_daily_loss")], bridge, make_snapshot())
    assert len(bridge.open_positions) == 1  # untouched


@pytest.fixture
def clear_live_confirm_env(monkeypatch):
    monkeypatch.delenv(LIVE_CONFIRM_ENV_VAR, raising=False)


def test_active_enforcer_refuses_to_construct_without_confirmation(clear_live_confirm_env):
    with pytest.raises(LiveExecutionNotConfirmed):
        ActiveEnforcer(RecordingAlerter(), allow_live_execution=True)


def test_active_enforcer_refuses_to_construct_with_only_env_var(clear_live_confirm_env, monkeypatch):
    monkeypatch.setenv(LIVE_CONFIRM_ENV_VAR, "YES")
    with pytest.raises(LiveExecutionNotConfirmed):
        ActiveEnforcer(RecordingAlerter(), allow_live_execution=False)


def test_hybrid_enforcer_closes_all_positions_on_max_daily_loss(monkeypatch):
    monkeypatch.setenv(LIVE_CONFIRM_ENV_VAR, "YES")
    position = Position(
        ticket=1,
        symbol="EURUSD",
        direction=TradeDirection.BUY,
        volume=0.1,
        open_price=1.1,
        open_time=NOW,
        stop_loss=1.09,
        take_profit=1.11,
        current_price=1.05,
        profit=-600.0,
    )
    bridge = MockMT5Client(open_positions=[position], live_execution_enabled=True)
    enforcer = HybridEnforcer(RecordingAlerter(), allow_live_execution=True)
    enforcer.handle([failed("max_daily_loss")], bridge, make_snapshot())
    assert bridge.open_positions == []


def test_hybrid_enforcer_closes_only_the_cooldown_violating_position(monkeypatch):
    monkeypatch.setenv(LIVE_CONFIRM_ENV_VAR, "YES")
    kept = Position(
        ticket=1,
        symbol="EURUSD",
        direction=TradeDirection.BUY,
        volume=0.1,
        open_price=1.1,
        open_time=NOW,
        stop_loss=1.09,
        take_profit=1.11,
        current_price=1.1,
        profit=5.0,
    )
    violating = Position(
        ticket=2,
        symbol="GBPUSD",
        direction=TradeDirection.BUY,
        volume=0.1,
        open_price=1.25,
        open_time=NOW,
        stop_loss=1.24,
        take_profit=1.26,
        current_price=1.25,
        profit=0.0,
    )
    bridge = MockMT5Client(open_positions=[kept, violating], live_execution_enabled=True)
    enforcer = HybridEnforcer(RecordingAlerter(), allow_live_execution=True)
    enforcer.handle([failed("consecutive_loss_cooldown", ticket=2)], bridge, make_snapshot())
    assert [p.ticket for p in bridge.open_positions] == [1]


def test_hybrid_enforcer_does_not_act_on_non_hard_safety_rules(monkeypatch):
    monkeypatch.setenv(LIVE_CONFIRM_ENV_VAR, "YES")
    position = Position(
        ticket=1,
        symbol="EURUSD",
        direction=TradeDirection.BUY,
        volume=0.1,
        open_price=1.1,
        open_time=NOW,
        stop_loss=None,
        take_profit=None,
        current_price=1.1,
        profit=0.0,
    )
    bridge = MockMT5Client(open_positions=[position], live_execution_enabled=True)
    enforcer = HybridEnforcer(RecordingAlerter(), allow_live_execution=True)
    enforcer.handle([failed("stop_loss_required", ticket=1)], bridge, make_snapshot())
    assert len(bridge.open_positions) == 1  # missing-SL isn't a hard safety rule; alert-only
