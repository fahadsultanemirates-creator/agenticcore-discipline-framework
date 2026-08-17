"""Wires everything together and runs the monitoring loop:

    MT5Bridge.get_account_snapshot()
        -> RuleEngine.evaluate()
        -> ComplianceLogger.log_cycle()   (always, every check, pass or fail)
        -> Enforcer.handle()              (alert in passive; alert + hard-safety
                                            action in active/hybrid)

See scripts/run_monitor.py for the CLI entrypoint.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from discipline_framework.alerts.telegram import Alerter, NullAlerter, TelegramAlerter
from discipline_framework.config import (
    PROJECT_ROOT,
    Settings,
    load_mt5_credentials,
    load_settings,
    load_telegram_credentials,
    load_trading_rules,
)
from discipline_framework.enforcement import Enforcer, build_enforcer
from discipline_framework.logging_stats.logger import ComplianceLogger, setup_logging
from discipline_framework.mt5_bridge.client import MT5_AVAILABLE, MetaTrader5Client
from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.mt5_bridge.mock_client import MockMT5Client
from discipline_framework.rules.engine import RuleEngine

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


class MonitoringLoop:
    def __init__(
        self,
        engine: RuleEngine,
        bridge: MT5Bridge,
        enforcer: Enforcer,
        compliance_logger: ComplianceLogger,
        poll_interval_seconds: int,
    ) -> None:
        self.engine = engine
        self.bridge = bridge
        self.enforcer = enforcer
        self.compliance_logger = compliance_logger
        self.poll_interval_seconds = poll_interval_seconds

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
            self.bridge.disconnect()


def _resolve_log_dir(settings: Settings) -> Path:
    log_dir = Path(settings.logging.log_dir)
    return log_dir if log_dir.is_absolute() else PROJECT_ROOT / log_dir


def build_monitoring_loop(use_mock: bool = False) -> MonitoringLoop:
    settings = load_settings()
    rules = load_trading_rules()
    log_dir = _resolve_log_dir(settings)

    setup_logging(
        log_dir=log_dir,
        audit_log_file=settings.logging.audit_log_file,
        level=settings.logging.level,
    )

    bridge = build_bridge(settings, use_mock=use_mock)
    alerter = build_alerter(settings)
    enforcer = build_enforcer(
        mode=settings.enforcement.mode,
        alerter=alerter,
        allow_live_execution=settings.enforcement.allow_live_execution,
    )
    compliance_logger = ComplianceLogger(log_dir / settings.logging.compliance_log_file)
    engine = RuleEngine(rules)

    if not bridge.connect():
        raise RuntimeError("Failed to connect to MT5 bridge")

    logger.info(
        "Configured: mode=%s, allow_live_execution=%s, telegram=%s",
        settings.enforcement.mode,
        settings.enforcement.allow_live_execution,
        type(alerter).__name__,
    )

    return MonitoringLoop(
        engine=engine,
        bridge=bridge,
        enforcer=enforcer,
        compliance_logger=compliance_logger,
        poll_interval_seconds=settings.monitoring.poll_interval_seconds,
    )


def main() -> None:
    build_monitoring_loop().run_forever()


if __name__ == "__main__":
    main()
