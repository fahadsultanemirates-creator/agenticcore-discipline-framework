from __future__ import annotations

from discipline_framework.enforcement.pausable import PausableEnforcer
from discipline_framework.mt5_bridge.mock_client import MockMT5Client
from discipline_framework.rules.models import CheckResult, Severity
from tests.test_rule_engine import make_snapshot


class RecordingEnforcer:
    mode_name = "passive"

    def __init__(self):
        self.alerter = object()
        self.calls = []

    def handle(self, results, bridge, snapshot):
        self.calls.append(results)


def failed(rule_id):
    return CheckResult(rule_id=rule_id, passed=False, severity=Severity.CRITICAL, message="x")


def test_delegates_to_inner_enforcer_when_enabled():
    inner = RecordingEnforcer()
    enforcer = PausableEnforcer(inner)
    results = [failed("stop_loss_required")]
    enforcer.handle(results, MockMT5Client(), make_snapshot())
    assert inner.calls == [results]


def test_pause_suppresses_handling():
    inner = RecordingEnforcer()
    enforcer = PausableEnforcer(inner)
    enforcer.pause()
    enforcer.handle([failed("max_daily_loss")], MockMT5Client(), make_snapshot())
    assert inner.calls == []
    assert enforcer.enabled is False


def test_resume_restores_handling():
    inner = RecordingEnforcer()
    enforcer = PausableEnforcer(inner)
    enforcer.pause()
    enforcer.resume()
    results = [failed("max_daily_loss")]
    enforcer.handle(results, MockMT5Client(), make_snapshot())
    assert inner.calls == [results]
    assert enforcer.enabled is True


def test_mode_name_delegates_to_inner():
    inner = RecordingEnforcer()
    enforcer = PausableEnforcer(inner)
    assert enforcer.mode_name == "passive"
