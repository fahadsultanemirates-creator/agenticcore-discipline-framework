"""Wires everything together and runs the monitoring loop:

    MT5Bridge.get_account_snapshot()
        -> RuleEngine.evaluate()          (reads live rules from RulesStore)
        -> ComplianceLogger.log_cycle()   (always, every check, pass or fail)
        -> Enforcer.handle()              (alert in passive; alert + hard-safety
                                            action in active/hybrid; no-op while
                                            /pause'd)

Alongside the loop, a TelegramCommandBot runs in its own thread, sharing the
same RulesStore and (Pausable)Enforcer — /setrisk et al. mutate the store
that RuleEngine reads from every cycle, and /pause toggles the enforcer's
`enabled` flag. See discipline_framework/commands/ and
docs/TELEGRAM_COMMANDS.md.

See scripts/run_monitor.py for the CLI entrypoint.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from discipline_framework.alerts.telegram import Alerter, NullAlerter, TelegramAlerter
from discipline_framework.commands import CommandHandlers, TelegramCommandBot
from discipline_framework.config import (
    DEFAULT_RULES_OVERRIDES_PATH,
    DEFAULT_RULES_PATH,
    PROJECT_ROOT,
    Settings,
    load_mt5_credentials,
    load_settings,
    load_telegram_credentials,
)
from discipline_framework.enforcement import Enforcer, PausableEnforcer, build_enforcer
from discipline_framework.logging_stats.logger import ComplianceLogger, setup_logging
from discipline_framework.mt5_bridge.client import MT5_AVAILABLE, MetaTrader5Client
from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.mt5_bridge.mock_client import MockMT5Client
from discipline_framework.rules.engine import RuleEngine
from discipline_framework.rules.store import RulesStore

logger = logging.getLogger("discipline_framework.main")


def build_bridge(settings: Settings, use_mock: bool) -> MT5Bridge:
    if use_mock or settings.mt5.force_mock or not MT5_AVAILABLE:
        if not use_mock and not settings.mt5.force_mock:
            logger.warning("MetaTrader5 package unavailable on this platform; using MockMT5Client")
        return MockMT5Client()

    creds = load_mt5_credentials()
    if creds.login is None or not creds.password or not creds.server:
        raise RuntimeError(
            "Real MT5 bridge requested but MT5_LOGIN/MT5_PASSWORD/MT5_SERVER "
            "are not set in the environment (.env). Fill those in, or run "
            "with --mock."
        )
    live_execution_enabled = settings.enforcement.mode != "passive" and settings.enforcement.allow_live_execution
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
        logger.warning("Telegram enabled but TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set; alerts will only be logged")
        return NullAlerter()
    return TelegramAlerter(
        bot_token=creds.bot_token,
        chat_id=creds.chat_id,
        min_severity=settings.telegram.min_severity,
    )


def build_command_bot(
    settings: Settings, rules_store: RulesStore, enforcer: PausableEnforcer
) -> TelegramCommandBot | None:
    if not settings.telegram.enabled or not settings.telegram.commands_enabled:
        return None
    creds = load_telegram_credentials()
    if not creds.bot_token:
        logger.warning("Telegram commands enabled but TELEGRAM_BOT_TOKEN not set; command interface disabled")
        return None
    handlers = CommandHandlers(rules_store=rules_store, enforcer=enforcer)
    return TelegramCommandBot(
        bot_token=creds.bot_token,
        handlers=handlers,
        authorized_user_ids=settings.telegram.authorized_user_ids,
    )


class MonitoringLoop:
    def __init__(
        self,
        engine: RuleEngine,
        bridge: MT5Bridge,
        enforcer: Enforcer,
        compliance_logger: ComplianceLogger,
        poll_interval_seconds: int,
        command_bot: TelegramCommandBot | None = None,
    ) -> None:
        self.engine = engine
        self.bridge = bridge
        self.enforcer = enforcer
        self.compliance_logger = compliance_logger
        self.poll_interval_seconds = poll_interval_seconds
        self.command_bot = command_bot
        self._command_bot_thread: threading.Thread | None = None

    def run_once(self):
        snapshot = self.bridge.get_account_snapshot()
        results = self.engine.evaluate(snapshot)
        self.compliance_logger.log_cycle(snapshot, results, self.enforcer.mode_name)
        self.enforcer.handle(results, self.bridge, snapshot)
        return results

    def run_forever(self) -> None:
        logger.info(
            "Monitoring loop started (mode=%s, poll_interval=%ss)",
            self.enforcer.mode_name,
            self.poll_interval_seconds,
        )
        if self.command_bot is not None:
            self._command_bot_thread = threading.Thread(
                target=self.command_bot.run_forever, name="telegram-commands", daemon=True
            )
            self._command_bot_thread.start()
        try:
            while True:
                try:
                    self.run_once()
                except Exception:
                    logger.exception("Error during monitoring cycle; will retry next cycle")
                time.sleep(self.poll_interval_seconds)
        except KeyboardInterrupt:
            logger.info("Interrupted by user, shutting down")
        finally:
            if self.command_bot is not None:
                self.command_bot.stop()
            self.bridge.disconnect()


def _resolve_log_dir(settings: Settings) -> Path:
    log_dir = Path(settings.logging.log_dir)
    return log_dir if log_dir.is_absolute() else PROJECT_ROOT / log_dir


def build_monitoring_loop(use_mock: bool = False) -> MonitoringLoop:
    settings = load_settings()
    log_dir = _resolve_log_dir(settings)

    setup_logging(
        log_dir=log_dir,
        audit_log_file=settings.logging.audit_log_file,
        level=settings.logging.level,
    )

    rules_store = RulesStore.load(DEFAULT_RULES_PATH, overrides_path=DEFAULT_RULES_OVERRIDES_PATH)
    bridge = build_bridge(settings, use_mock=use_mock)
    alerter = build_alerter(settings)
    enforcer = PausableEnforcer(
        build_enforcer(
            mode=settings.enforcement.mode,
            alerter=alerter,
            allow_live_execution=settings.enforcement.allow_live_execution,
        )
    )
    compliance_logger = ComplianceLogger(log_dir / settings.logging.compliance_log_file)
    engine = RuleEngine(rules_store)
    command_bot = build_command_bot(settings, rules_store, enforcer)

    if not bridge.connect():
        raise RuntimeError("Failed to connect to MT5 bridge")

    logger.info(
        "Configured: mode=%s, allow_live_execution=%s, telegram=%s, commands=%s",
        settings.enforcement.mode,
        settings.enforcement.allow_live_execution,
        type(alerter).__name__,
        "enabled" if command_bot else "disabled",
    )
    if rules_store.overrides:
        logger.info("Loaded live rule overrides from a previous session: %s", rules_store.overrides)

    return MonitoringLoop(
        engine=engine,
        bridge=bridge,
        enforcer=enforcer,
        compliance_logger=compliance_logger,
        poll_interval_seconds=settings.monitoring.poll_interval_seconds,
        command_bot=command_bot,
    )


def main() -> None:
    build_monitoring_loop().run_forever()


if __name__ == "__main__":
    main()
