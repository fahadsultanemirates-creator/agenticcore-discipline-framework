"""Telegram alerting.

Deliberately dumb: one HTTP POST per alert to the Bot API, no queuing, no
retries beyond what `requests` gives us. A failed alert is logged loudly but
never raises — a Telegram outage must not take down the monitoring loop,
since that loop is the thing actually protecting the account.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import requests

from discipline_framework.rules.models import CheckResult, Severity

logger = logging.getLogger("discipline_framework.alerts")

TELEGRAM_API_BASE = "https://api.telegram.org"

SEVERITY_EMOJI = {
    Severity.INFO: "ℹ️",
    Severity.WARNING: "⚠️",
    Severity.CRITICAL: "🚨",
}


class Alerter(ABC):
    @abstractmethod
    def send(self, text: str) -> bool:
        """Send a raw message. Returns True on success."""

    def send_violation(self, result: CheckResult, mode: str) -> bool:
        emoji = SEVERITY_EMOJI.get(result.severity, "")
        text = (
            f"{emoji} <b>{result.severity.value.upper()}</b> [{mode}] "
            f"<code>{result.rule_id}</code>\n{result.message}"
        )
        return self.send(text)


class NullAlerter(Alerter):
    """No-op alerter used when Telegram isn't configured. Logs instead of
    sending, so nothing is silently dropped."""

    def send(self, text: str) -> bool:
        logger.info("[NullAlerter, no Telegram configured] %s", text)
        return True


class TelegramAlerter(Alerter):
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        min_severity: Severity = Severity.WARNING,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._min_severity = min_severity
        self._timeout_seconds = timeout_seconds

    def send(self, text: str) -> bool:
        url = f"{TELEGRAM_API_BASE}/bot{self._bot_token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"}
        try:
            response = requests.post(url, json=payload, timeout=self._timeout_seconds)
            response.raise_for_status()
            return True
        except requests.RequestException:
            logger.exception("Failed to send Telegram alert")
            return False

    def send_violation(self, result: CheckResult, mode: str) -> bool:
        if result.severity.rank < self._min_severity.rank:
            return True  # below the configured threshold; not an error, just filtered
        return super().send_violation(result, mode)

    def test_connection(self) -> bool:
        """Verify the bot token/chat_id work. Call this once at startup so a
        misconfigured Telegram setup is caught immediately, not the first
        time a real rule violation needs to be alerted."""
        return self.send("✅ discipline_framework: Telegram alerting is connected.")
