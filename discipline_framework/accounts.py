"""Per-account runtime: bundles everything one MT5 account needs (bridge,
rules, enforcement, logging) and runs its own monitoring loop, independent
of every other account.

One AccountRuntime/AccountWorker per account rather than one shared engine
looping over account ids, because each account has its own rule set, its
own enforcement mode / live-execution posture, and — critically — its own
MT5 terminal connection. The official MetaTrader5 Python package only
supports one active terminal connection per OS process, so
AccountWorker.run_forever() is written to be safe to run either as a thread
within one process (fine for the mock bridge, and for real MT5 as long as
only one account in that process uses the real bridge) or as the entire
content of its own process — the latter is the recommended production
topology once more than one account is on the real bridge. See
docs/MULTI_ACCOUNT.md and scripts/run_account.py.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from discipline_framework.alerts.telegram import Alerter, NullAlerter, TelegramAlerter
from discipline_framework.config import (
    AccountConfig,
    Settings,
    control_state_path_for,
    load_mt5_credentials,
    load_telegram_credentials,
    rules_overrides_path_for,
    rules_path_for,
)
from discipline_framework.enforcement import PausableEnforcer, build_enforcer
from discipline_framework.logging_stats.logger import ComplianceLogger
from discipline_framework.mt5_bridge.client import MT5_AVAILABLE, MetaTrader5Client
from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.mt5_bridge.mock_client import MockMT5Client
from discipline_framework.rules.engine import RuleEngine
from discipline_framework.rules.store import RulesStore

logger = logging.getLogger("discipline_framework.accounts")


def build_bridge(account: AccountConfig, settings: Settings, use_mock: bool) -> MT5Bridge:
    if use_mock or settings.mt5.force_mock or not MT5_AVAILABLE:
        if not use_mock and not settings.mt5.force_mock:
            logger.warning(
                "[%s] MetaTrader5 package unavailable on this platform; using MockMT5Client", account.id
            )
        return MockMT5Client()

    creds = load_mt5_credentials(account)
    if creds.login is None or not creds.password or not creds.server:
        raise RuntimeError(
            f"Account '{account.id}': real MT5 bridge requested but "
            f"{account.mt5.login_env}/{account.mt5.password_env}/{account.mt5.server_env} "
            "are not all set in the environment (.env). Fill those in, or run with --mock."
        )
    live_execution_enabled = account.enforcement.mode != "passive" and account.enforcement.allow_live_execution
    return MetaTrader5Client(
        login=creds.login,
        password=creds.password,
        server=creds.server,
        terminal_path=creds.terminal_path,
        history_lookback_days=settings.monitoring.history_lookback_days,
        live_execution_enabled=live_execution_enabled,
    )


def build_alerter(settings: Settings) -> Alerter:
    if not settings.telegram.enabled:
        return NullAlerter()
    creds = load_telegram_credentials()
    if not creds.bot_token or not creds.chat_id:
        logger.warning(
            "Telegram enabled but TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set; alerts will only be logged"
        )
        return NullAlerter()
    return TelegramAlerter(
        bot_token=creds.bot_token, chat_id=creds.chat_id, min_severity=settings.telegram.min_severity
    )


@dataclass
class AccountRuntime:
    """Everything one account needs: its own bridge, its own live rules
    store, its own (pausable) enforcer, its own rule engine, its own
    compliance log. Nothing here is shared with any other account — the
    Telegram bot is the only thing that touches more than one of these."""

    account: AccountConfig
    bridge: MT5Bridge
    rules_store: RulesStore
    enforcer: PausableEnforcer
    engine: RuleEngine
    compliance_logger: ComplianceLogger


def build_account_runtime(
    account: AccountConfig,
    settings: Settings,
    alerter: Alerter,
    compliance_log_dir: Path,
    use_mock: bool = False,
) -> AccountRuntime:
    rules_store = RulesStore.load(rules_path_for(account), overrides_path=rules_overrides_path_for(account))
    bridge = build_bridge(account, settings, use_mock=use_mock)
    enforcer = PausableEnforcer(
        build_enforcer(
            mode=account.enforcement.mode,
            alerter=alerter,
            allow_live_execution=account.enforcement.allow_live_execution,
        ),
        state_path=control_state_path_for(account),
    )
    return AccountRuntime(
        account=account,
        bridge=bridge,
        rules_store=rules_store,
        enforcer=enforcer,
        engine=RuleEngine(rules_store),
        compliance_logger=ComplianceLogger(compliance_log_dir / f"{account.id}.jsonl"),
    )


class AccountWorker:
    """Runs one account's monitoring cycle forever: reload live state,
    pull MT5 state, check rules, log, enforce. Reloading rules/pause state
    from disk first means a Telegram command — whether issued in this same
    process or a different one — takes effect on the very next cycle."""

    def __init__(self, runtime: AccountRuntime, poll_interval_seconds: int) -> None:
        self.runtime = runtime
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()

    @property
    def account_id(self) -> str:
        return self.runtime.account.id

    def stop(self) -> None:
        self._stop_event.set()

    def run_once(self):
        self.runtime.rules_store.reload_if_stale()
        self.runtime.enforcer.sync_from_disk()
        snapshot = self.runtime.bridge.get_account_snapshot()
        results = self.runtime.engine.evaluate(snapshot)
        self.runtime.compliance_logger.log_cycle(
            snapshot, results, self.runtime.enforcer.mode_name, account_id=self.account_id
        )
        self.runtime.enforcer.handle(results, self.runtime.bridge, snapshot)
        return results

    def run_forever(self) -> None:
        logger.info(
            "[%s] Account worker started (mode=%s, poll_interval=%ss)",
            self.account_id,
            self.runtime.enforcer.mode_name,
            self.poll_interval_seconds,
        )
        if not self.runtime.bridge.connect():
            logger.error("[%s] Failed to connect to MT5 bridge; worker exiting", self.account_id)
            return
        try:
            while not self._stop_event.is_set():
                try:
                    self.run_once()
                except Exception:
                    logger.exception("[%s] Error during monitoring cycle; will retry next cycle", self.account_id)
                self._stop_event.wait(self.poll_interval_seconds)
        finally:
            self.runtime.bridge.disconnect()
            logger.info("[%s] Account worker stopped", self.account_id)
