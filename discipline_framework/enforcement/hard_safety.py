"""The two hard safety actions shared by active and hybrid mode: closing
everything on a max-daily-loss breach, and closing anything opened during a
mandatory post-loss cooldown. Kept in one place so both modes act on these
identically — passive mode never calls this."""

from __future__ import annotations

import logging

from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.rules.models import CheckResult

logger = logging.getLogger("discipline_framework.enforcement.hard_safety")

HARD_SAFETY_RULE_IDS = {"max_daily_loss", "max_daily_loss_open_positions", "consecutive_loss_cooldown"}


def enforce_hard_safety(result: CheckResult, bridge: MT5Bridge, mode_name: str) -> bool:
    """Acts on a failed hard-safety check. Returns True if an action was taken."""
    if result.passed or result.rule_id not in HARD_SAFETY_RULE_IDS:
        return False

    if result.rule_id in ("max_daily_loss", "max_daily_loss_open_positions"):
        logger.critical("[%s] Max daily loss breached — closing all open positions", mode_name)
        bridge.close_all_positions()
        return True

    if result.rule_id == "consecutive_loss_cooldown":
        ticket = result.context.get("ticket")
        if ticket is not None:
            logger.critical(
                "[%s] Closing position #%s opened during mandatory cooldown", mode_name, ticket
            )
            bridge.close_position(ticket)
            return True

    return False
