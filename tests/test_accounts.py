from __future__ import annotations

from discipline_framework.accounts import AccountWorker, build_account_runtime
from discipline_framework.alerts.telegram import NullAlerter
from discipline_framework.mt5_bridge.mock_client import MockMT5Client
from discipline_framework.rules.store import RulesStore


def test_build_account_runtime_uses_mock_bridge(isolated_state_dirs, make_account_config, settings, tmp_path):
    account = make_account_config(account_id="account_1")
    runtime = build_account_runtime(account, settings, NullAlerter(), tmp_path / "compliance", use_mock=True)

    assert isinstance(runtime.bridge, MockMT5Client)
    assert runtime.account.id == "account_1"
    assert runtime.compliance_logger.path == tmp_path / "compliance" / "account_1.jsonl"


def test_two_account_runtimes_do_not_share_rules_state(isolated_state_dirs, make_account_config, settings, tmp_path):
    account_1 = make_account_config(account_id="account_1")
    account_2 = make_account_config(account_id="account_2")
    runtime_1 = build_account_runtime(account_1, settings, NullAlerter(), tmp_path / "compliance", use_mock=True)
    runtime_2 = build_account_runtime(account_2, settings, NullAlerter(), tmp_path / "compliance", use_mock=True)

    runtime_1.rules_store.set_max_risk_per_trade_pct(1.0)
    assert runtime_1.rules_store.rules.risk.max_risk_per_trade_pct == 1.0
    assert runtime_2.rules_store.rules.risk.max_risk_per_trade_pct != 1.0

    runtime_1.enforcer.pause()
    assert runtime_1.enforcer.enabled is False
    assert runtime_2.enforcer.enabled is True


def test_account_worker_run_once_logs_with_account_id(make_account_runtime):
    runtime = make_account_runtime(account_id="account_1")
    runtime.bridge.connect()
    worker = AccountWorker(runtime, poll_interval_seconds=30)

    results = worker.run_once()

    assert len(results) > 0
    assert runtime.enforcer._inner.calls == [results]  # the recording inner enforcer saw this cycle
    with runtime.compliance_logger.path.open() as f:
        import json

        record = json.loads(f.readline())
    assert record["account_id"] == "account_1"


def test_account_worker_skips_enforcement_while_paused(make_account_runtime):
    runtime = make_account_runtime(account_id="account_1")
    runtime.bridge.connect()
    runtime.enforcer.pause()
    worker = AccountWorker(runtime, poll_interval_seconds=30)

    worker.run_once()

    assert runtime.enforcer._inner.calls == []  # never reached the inner enforcer while paused


def test_account_worker_picks_up_a_rule_change_from_another_process(
    isolated_state_dirs, make_account_config, settings, tmp_path
):
    """Simulates the real production topology: a Telegram bot process
    writes an override to disk, and a separately-running AccountWorker
    picks it up on its next cycle via RulesStore.reload_if_stale() — no
    shared in-memory object between the two, only the filesystem."""
    account = make_account_config(account_id="account_1")
    worker_runtime = build_account_runtime(account, settings, NullAlerter(), tmp_path / "compliance", use_mock=True)
    worker_runtime.bridge.connect()
    worker = AccountWorker(worker_runtime, poll_interval_seconds=30)

    original_risk = worker_runtime.rules_store.rules.risk.max_risk_per_trade_pct

    # A second RulesStore pointed at the same files, standing in for the
    # bot process.
    from discipline_framework.config import rules_overrides_path_for, rules_path_for

    bot_side_store = RulesStore.load(
        rules_path_for(account), overrides_path=rules_overrides_path_for(account)
    )
    bot_side_store.set_max_risk_per_trade_pct(original_risk + 5)

    assert worker_runtime.rules_store.rules.risk.max_risk_per_trade_pct == original_risk  # not yet reloaded

    worker.run_once()

    assert worker_runtime.rules_store.rules.risk.max_risk_per_trade_pct == original_risk + 5


def test_account_worker_picks_up_pause_from_another_process(
    isolated_state_dirs, make_account_config, settings, tmp_path
):
    from discipline_framework.config import control_state_path_for
    from discipline_framework.enforcement.pausable import PausableEnforcer

    account = make_account_config(account_id="account_1")
    worker_runtime = build_account_runtime(account, settings, NullAlerter(), tmp_path / "compliance", use_mock=True)
    worker_runtime.bridge.connect()
    worker = AccountWorker(worker_runtime, poll_interval_seconds=30)

    class Inner:
        mode_name = "passive"

        def __init__(self):
            self.alerter = object()
            self.calls = []

        def handle(self, results, bridge, snapshot):
            self.calls.append(results)

    # A second, independent PausableEnforcer pointed at the same state
    # file, standing in for the bot process.
    bot_side_enforcer = PausableEnforcer(Inner(), state_path=control_state_path_for(account))
    bot_side_enforcer.pause()

    assert worker_runtime.enforcer.enabled is True  # not yet synced

    worker.run_once()

    assert worker_runtime.enforcer.enabled is False
