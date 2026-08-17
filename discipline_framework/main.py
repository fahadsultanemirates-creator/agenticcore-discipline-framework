"""Wires together and runs a multi-account deployment:

    for each enabled account (config/accounts.yaml):
        AccountWorker.run_forever() in its own thread
            MT5Bridge.get_account_snapshot()
                -> RuleEngine.evaluate()          (that account's live RulesStore)
                -> ComplianceLogger.log_cycle()   (always, tagged with account_id)
                -> Enforcer.handle()              (per that account's mode; no-op while paused)

    + one shared TelegramCommandBot thread — commands name an account_id
      and are routed to that account's AccountRuntime.

MultiAccountSupervisor (this module) runs every account in ONE process —
fine for the mock bridge, and for real MT5 as long as at most one account
in the process uses the real bridge (the MetaTrader5 SDK only supports one
terminal connection per process). For a real multi-account deployment with
more than one live account, run each account standalone instead:
scripts/run_account.py <account_id> (one process per account) plus
scripts/run_bot.py (the shared Telegram interface, no MT5 connection of its
own). Both topologies use the exact same AccountRuntime/AccountWorker code
and coordinate through the same on-disk rules/pause state either way — see
docs/MULTI_ACCOUNT.md.

See scripts/run_monitor.py for this module's CLI entrypoint.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from discipline_framework.accounts import AccountRuntime, AccountWorker, build_account_runtime, build_alerter
from discipline_framework.commands import CommandHandlers, TelegramCommandBot
from discipline_framework.config import (
    DEFAULT_ACCOUNTS_PATH,
    PROJECT_ROOT,
    Settings,
    load_accounts,
    load_settings,
    load_telegram_credentials,
)
from discipline_framework.logging_stats.logger import setup_logging

logger = logging.getLogger("discipline_framework.main")


def build_command_bot(settings: Settings, accounts: dict[str, AccountRuntime]) -> TelegramCommandBot | None:
    if not settings.telegram.enabled or not settings.telegram.commands_enabled:
        return None
    creds = load_telegram_credentials()
    if not creds.bot_token:
        logger.warning("Telegram commands enabled but TELEGRAM_BOT_TOKEN not set; command interface disabled")
        return None
    return TelegramCommandBot(
        bot_token=creds.bot_token,
        handlers=CommandHandlers(accounts=accounts),
        authorized_user_ids=settings.telegram.authorized_user_ids,
    )


def _resolve_log_dir(settings: Settings) -> Path:
    log_dir = Path(settings.logging.log_dir)
    return log_dir if log_dir.is_absolute() else PROJECT_ROOT / log_dir


class MultiAccountSupervisor:
    def __init__(
        self,
        workers: list[AccountWorker],
        command_bot: TelegramCommandBot | None,
    ) -> None:
        self.workers = workers
        self.command_bot = command_bot
        self._worker_threads: list[threading.Thread] = []
        self._bot_thread: threading.Thread | None = None

    def run_forever(self) -> None:
        logger.info(
            "Starting %d account worker(s): %s",
            len(self.workers),
            ", ".join(w.account_id for w in self.workers),
        )
        for worker in self.workers:
            thread = threading.Thread(
                target=worker.run_forever, name=f"account-{worker.account_id}", daemon=True
            )
            self._worker_threads.append(thread)
            thread.start()

        if self.command_bot is not None:
            self._bot_thread = threading.Thread(
                target=self.command_bot.run_forever, name="telegram-commands", daemon=True
            )
            self._bot_thread.start()

        try:
            while any(t.is_alive() for t in self._worker_threads):
                for t in self._worker_threads:
                    t.join(timeout=1.0)
        except KeyboardInterrupt:
            logger.info("Interrupted by user, shutting down")
        else:
            logger.error("All account workers have stopped; shutting down")
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        for worker in self.workers:
            worker.stop()
        if self.command_bot is not None:
            self.command_bot.stop()
        for t in self._worker_threads:
            t.join(timeout=10)
        if self._bot_thread is not None:
            self._bot_thread.join(timeout=10)


def build_supervisor(use_mock: bool = False) -> MultiAccountSupervisor:
    settings = load_settings()
    log_dir = _resolve_log_dir(settings)

    setup_logging(
        log_dir=log_dir,
        audit_log_file=settings.logging.audit_log_file,
        level=settings.logging.level,
    )

    compliance_log_dir = log_dir / settings.logging.compliance_log_dir
    alerter = build_alerter(settings)

    accounts = [a for a in load_accounts() if a.enabled]
    if not accounts:
        raise RuntimeError(f"No enabled accounts in {DEFAULT_ACCOUNTS_PATH}")

    runtimes: dict[str, AccountRuntime] = {}
    workers: list[AccountWorker] = []
    for account in accounts:
        runtime = build_account_runtime(account, settings, alerter, compliance_log_dir, use_mock=use_mock)
        runtimes[account.id] = runtime
        workers.append(AccountWorker(runtime, poll_interval_seconds=settings.monitoring.poll_interval_seconds))

        logger.info(
            "[%s] Configured: mode=%s, allow_live_execution=%s",
            account.id,
            account.enforcement.mode,
            account.enforcement.allow_live_execution,
        )
        if runtime.rules_store.overrides:
            logger.info(
                "[%s] Loaded live rule overrides from a previous session: %s",
                account.id,
                runtime.rules_store.overrides,
            )

    command_bot = build_command_bot(settings, runtimes)
    logger.info(
        "Telegram: alerts=%s, commands=%s",
        type(alerter).__name__,
        "enabled" if command_bot else "disabled",
    )

    return MultiAccountSupervisor(workers=workers, command_bot=command_bot)


def build_single_account_worker(account_id: str, use_mock: bool = False) -> AccountWorker:
    """Builds one account's worker in isolation, with no other account's
    state touched — the entrypoint for scripts/run_account.py, the
    recommended way to run more than one account against the real MT5
    bridge simultaneously (each in its own OS process)."""
    settings = load_settings()
    log_dir = _resolve_log_dir(settings)

    setup_logging(
        log_dir=log_dir,
        audit_log_file=settings.logging.audit_log_file,
        level=settings.logging.level,
    )

    accounts_by_id = {a.id: a for a in load_accounts()}
    account = accounts_by_id.get(account_id)
    if account is None:
        raise ValueError(f"Unknown account '{account_id}'. Known accounts: {', '.join(accounts_by_id) or '(none)'}")
    if not account.enabled:
        raise ValueError(f"Account '{account_id}' is disabled in {DEFAULT_ACCOUNTS_PATH}")

    compliance_log_dir = log_dir / settings.logging.compliance_log_dir
    alerter = build_alerter(settings)
    runtime = build_account_runtime(account, settings, alerter, compliance_log_dir, use_mock=use_mock)

    logger.info(
        "[%s] Configured: mode=%s, allow_live_execution=%s",
        account.id,
        account.enforcement.mode,
        account.enforcement.allow_live_execution,
    )
    return AccountWorker(runtime, poll_interval_seconds=settings.monitoring.poll_interval_seconds)


def build_command_only_bot(use_mock: bool = False) -> TelegramCommandBot:
    """Builds a Telegram command bot with access to every enabled account's
    RulesStore/PausableEnforcer, but never connects any of their MT5
    bridges — the entrypoint for scripts/run_bot.py, for running the
    command interface as its own process, separate from any account's
    monitoring loop. This process only reads/writes each account's rules
    and pause state on disk; the actual monitoring happens wherever that
    account's AccountWorker is running (in-process via run_monitor.py, or
    standalone via run_account.py)."""
    settings = load_settings()
    log_dir = _resolve_log_dir(settings)

    setup_logging(
        log_dir=log_dir,
        audit_log_file=settings.logging.audit_log_file,
        level=settings.logging.level,
    )

    compliance_log_dir = log_dir / settings.logging.compliance_log_dir
    alerter = build_alerter(settings)

    accounts = [a for a in load_accounts() if a.enabled]
    if not accounts:
        raise RuntimeError(f"No enabled accounts in {DEFAULT_ACCOUNTS_PATH}")

    runtimes = {
        account.id: build_account_runtime(account, settings, alerter, compliance_log_dir, use_mock=use_mock)
        for account in accounts
    }
    command_bot = build_command_bot(settings, runtimes)
    if command_bot is None:
        raise RuntimeError("Telegram commands are disabled, or TELEGRAM_BOT_TOKEN is not set — nothing to run.")
    return command_bot


def main() -> None:
    build_supervisor().run_forever()


if __name__ == "__main__":
    main()
