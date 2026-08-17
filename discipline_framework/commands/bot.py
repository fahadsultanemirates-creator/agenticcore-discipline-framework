"""Long-polls Telegram's getUpdates for /commands and dispatches them.

Runs in its own background thread (see main.py) so it never blocks the
monitoring loop — the two share a RulesStore and a PausableEnforcer, both
of which are internally lock-protected, so this can run fully concurrently
with rule evaluation.

Access control: authorized_user_ids is a whitelist of Telegram numeric user
IDs (config/settings.yaml: telegram.authorized_user_ids). Empty list means
open access — intended only for development/testing, and logged loudly on
every startup and every command so an empty whitelist is never silently
forgotten about. Set it to just the client's user ID before handing this
off with real money on the line.
"""

from __future__ import annotations

import logging
import threading
import time

import requests

from discipline_framework.commands.handlers import CommandHandlers

logger = logging.getLogger("discipline_framework.commands")

TELEGRAM_API_BASE = "https://api.telegram.org"
NOT_AUTHORIZED_MESSAGE = "🚫 Not authorized. This bot is restricted to approved users only."


class TelegramCommandBot:
    def __init__(
        self,
        bot_token: str,
        handlers: CommandHandlers,
        authorized_user_ids: list[int] | None = None,
        poll_timeout_seconds: int = 25,
    ) -> None:
        self._bot_token = bot_token
        self._handlers = handlers
        self._authorized_user_ids = set(authorized_user_ids or [])
        self._poll_timeout_seconds = poll_timeout_seconds
        self._offset = 0
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run_forever(self) -> None:
        if self._authorized_user_ids:
            logger.info(
                "Telegram command listener started (%d authorized user(s))",
                len(self._authorized_user_ids),
            )
        else:
            logger.warning(
                "Telegram command listener started with NO authorized_user_ids configured — "
                "ANYONE who messages this bot can change live trading rules. This is fine for "
                "testing; set telegram.authorized_user_ids in config/settings.yaml before "
                "handing this off with real money on the line."
            )
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except requests.RequestException:
                logger.exception("Telegram getUpdates failed; retrying in 5s")
                time.sleep(5)

    def _poll_once(self) -> None:
        url = f"{TELEGRAM_API_BASE}/bot{self._bot_token}/getUpdates"
        params = {"offset": self._offset, "timeout": self._poll_timeout_seconds}
        response = requests.get(url, params=params, timeout=self._poll_timeout_seconds + 10)
        response.raise_for_status()
        for update in response.json().get("result", []):
            self._offset = update["update_id"] + 1
            self._handle_update(update)

    def _handle_update(self, update: dict) -> None:
        message = update.get("message") or update.get("edited_message")
        if not message or "text" not in message:
            return

        text = message["text"].strip()
        if not text.startswith("/"):
            return

        chat_id = message["chat"]["id"]
        user_id = message.get("from", {}).get("id")
        command, *args = text.split()
        command = command[1:].split("@", 1)[0].lower()  # strip leading "/" and "@botname"

        if self._authorized_user_ids and user_id not in self._authorized_user_ids:
            logger.warning("Unauthorized command attempt: user_id=%s text=%r", user_id, text)
            self._reply(chat_id, NOT_AUTHORIZED_MESSAGE)
            return

        logger.info("Command from user_id=%s: %s", user_id, text)
        reply_text = self._handlers.dispatch(command, args)
        self._reply(chat_id, reply_text)

    def _reply(self, chat_id: int, text: str) -> None:
        url = f"{TELEGRAM_API_BASE}/bot{self._bot_token}/sendMessage"
        try:
            response = requests.post(
                url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10
            )
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to send Telegram command reply")
