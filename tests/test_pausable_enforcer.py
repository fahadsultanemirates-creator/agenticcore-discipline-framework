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


def test_sync_from_disk_noop_without_a_state_path():
    enforcer = PausableEnforcer(RecordingEnforcer())
    assert enforcer.sync_from_disk() is False
    assert enforcer.enabled is True


def test_pause_persists_and_a_second_instance_picks_it_up_via_sync(tmp_path):
    """The mechanism that lets a Telegram bot process and an account
    worker process coordinate pause state through nothing but the
    filesystem."""
    state_path = tmp_path / "account_1.json"
    worker_side = PausableEnforcer(RecordingEnforcer(), state_path=state_path)
    bot_side = PausableEnforcer(RecordingEnforcer(), state_path=state_path)

    bot_side.pause()
    assert worker_side.enabled is True  # not yet synced

    assert worker_side.sync_from_disk() is True
    assert worker_side.enabled is False
    assert worker_side.sync_from_disk() is False  # already up to date

    bot_side.resume()
    assert worker_side.sync_from_disk() is True
    assert worker_side.enabled is True


def test_new_instance_reads_existing_state_file_on_construction(tmp_path):
    state_path = tmp_path / "account_1.json"
    PausableEnforcer(RecordingEnforcer(), state_path=state_path).pause()

    fresh = PausableEnforcer(RecordingEnforcer(), state_path=state_path)
    assert fresh.enabled is False


def test_corrupt_state_file_fails_safe_to_enabled(tmp_path):
    state_path = tmp_path / "account_1.json"
    state_path.write_text("not valid json")

    enforcer = PausableEnforcer(RecordingEnforcer(), state_path=state_path)
    assert enforcer.enabled is True
