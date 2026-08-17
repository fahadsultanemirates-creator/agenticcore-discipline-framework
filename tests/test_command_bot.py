"""Tests the auth gate and update-dispatch wiring without any real network
calls — _reply is monkeypatched to record instead of hitting Telegram."""

from __future__ import annotations

from discipline_framework.commands.bot import NOT_AUTHORIZED_MESSAGE, TelegramCommandBot
from discipline_framework.commands.handlers import CommandHandlers


def make_bot(make_account_runtime, rules, authorized_user_ids=None):
    runtime = make_account_runtime(account_id="account_1", rules=rules)
    handlers = CommandHandlers({"account_1": runtime})
    bot = TelegramCommandBot("fake-token", handlers, authorized_user_ids=authorized_user_ids)
    replies = []
    bot._reply = lambda chat_id, text: replies.append((chat_id, text))
    return bot, runtime, replies


def message(text, user_id=111, chat_id=222):
    return {"message": {"text": text, "chat": {"id": chat_id}, "from": {"id": user_id}}}


def test_open_whitelist_allows_any_user(make_account_runtime, rules):
    bot, runtime, replies = make_bot(make_account_runtime, rules, authorized_user_ids=[])
    bot._handle_update(message("/setrisk account_1 1.5"))
    assert runtime.rules_store.rules.risk.max_risk_per_trade_pct == 1.5
    assert replies[0][1].startswith("✅")


def test_whitelisted_user_is_allowed(make_account_runtime, rules):
    bot, runtime, replies = make_bot(make_account_runtime, rules, authorized_user_ids=[111])
    bot._handle_update(message("/setrisk account_1 1.5", user_id=111))
    assert runtime.rules_store.rules.risk.max_risk_per_trade_pct == 1.5


def test_non_whitelisted_user_is_rejected(make_account_runtime, rules):
    bot, runtime, replies = make_bot(make_account_runtime, rules, authorized_user_ids=[111])
    bot._handle_update(message("/setrisk account_1 1.5", user_id=999))
    assert runtime.rules_store.rules.risk.max_risk_per_trade_pct == rules.risk.max_risk_per_trade_pct
    assert replies == [(222, NOT_AUTHORIZED_MESSAGE)]


def test_non_command_text_is_ignored(make_account_runtime, rules):
    bot, runtime, replies = make_bot(make_account_runtime, rules, authorized_user_ids=[])
    bot._handle_update({"message": {"text": "hey what's up", "chat": {"id": 222}, "from": {"id": 111}}})
    assert replies == []


def test_command_with_botname_suffix_is_parsed(make_account_runtime, rules):
    bot, runtime, replies = make_bot(make_account_runtime, rules, authorized_user_ids=[])
    bot._handle_update(message("/status@my_discipline_bot account_1"))
    assert len(replies) == 1
    assert "Enforcement" in replies[0][1]


def test_offset_advances_past_processed_update(make_account_runtime, rules):
    bot, runtime, replies = make_bot(make_account_runtime, rules, authorized_user_ids=[])
    bot._offset = 0
    update = {"update_id": 42, **message("/status account_1")}
    for u in [update]:
        bot._offset = u["update_id"] + 1
        bot._handle_update(u)
    assert bot._offset == 43
