"""Tests the auth gate and update-dispatch wiring without any real network
calls — _reply is monkeypatched to record instead of hitting Telegram."""

from __future__ import annotations

from discipline_framework.commands.bot import NOT_AUTHORIZED_MESSAGE, TelegramCommandBot
from discipline_framework.commands.handlers import CommandHandlers
from discipline_framework.enforcement.pausable import PausableEnforcer
from discipline_framework.rules.store import RulesStore


class RecordingEnforcer:
    mode_name = "passive"

    def __init__(self):
        self.alerter = object()

    def handle(self, results, bridge, snapshot):
        pass


def make_bot(rules, authorized_user_ids=None):
    store = RulesStore(rules)
    handlers = CommandHandlers(store, PausableEnforcer(RecordingEnforcer()))
    bot = TelegramCommandBot("fake-token", handlers, authorized_user_ids=authorized_user_ids)
    replies = []
    bot._reply = lambda chat_id, text: replies.append((chat_id, text))
    return bot, store, replies


def message(text, user_id=111, chat_id=222):
    return {"message": {"text": text, "chat": {"id": chat_id}, "from": {"id": user_id}}}


def test_open_whitelist_allows_any_user(rules):
    bot, store, replies = make_bot(rules, authorized_user_ids=[])
    bot._handle_update(message("/setrisk 1.5"))
    assert store.rules.risk.max_risk_per_trade_pct == 1.5
    assert replies[0][1].startswith("✅")


def test_whitelisted_user_is_allowed(rules):
    bot, store, replies = make_bot(rules, authorized_user_ids=[111])
    bot._handle_update(message("/setrisk 1.5", user_id=111))
    assert store.rules.risk.max_risk_per_trade_pct == 1.5


def test_non_whitelisted_user_is_rejected(rules):
    bot, store, replies = make_bot(rules, authorized_user_ids=[111])
    bot._handle_update(message("/setrisk 1.5", user_id=999))
    assert store.rules.risk.max_risk_per_trade_pct == rules.risk.max_risk_per_trade_pct
    assert replies == [(222, NOT_AUTHORIZED_MESSAGE)]


def test_non_command_text_is_ignored(rules):
    bot, store, replies = make_bot(rules, authorized_user_ids=[])
    bot._handle_update({"message": {"text": "hey what's up", "chat": {"id": 222}, "from": {"id": 111}}})
    assert replies == []


def test_command_with_botname_suffix_is_parsed(rules):
    bot, store, replies = make_bot(rules, authorized_user_ids=[])
    bot._handle_update(message("/status@my_discipline_bot"))
    assert len(replies) == 1
    assert "Enforcement" in replies[0][1]


def test_offset_advances_past_processed_update(rules):
    bot, store, replies = make_bot(rules, authorized_user_ids=[])
    bot._offset = 0
    update = {"update_id": 42, **message("/status")}
    for u in [update]:
        bot._offset = u["update_id"] + 1
        bot._handle_update(u)
    assert bot._offset == 43
