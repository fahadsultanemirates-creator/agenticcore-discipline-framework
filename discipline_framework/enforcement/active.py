"""Active mode: can auto-execute exits per the encoded rules.

Right now that's scoped to the same two hard safety cutoffs as hybrid mode
(see hard_safety.py) — max daily loss and cooldown violations. Everything
else (missing SL/TP, oversized risk, wrong symbol/session/trade-count) is
alert-only for now. That's not a code limitation, it's a judgment call: we
don't yet have the client's confirmed exact rules for what "auto-close a
mistargeted position" should mean per rule, and auto-acting on a placeholder
number would be worse than doing nothing. Expand the branch in handle()
below once those numbers are confirmed with the client.

Requires the live-execution safety gate (see base.py) to even construct.
"""

from __future__ import annotations

import logging

from discipline_framework.enforcement.base import Enforcer, require_live_execution_confirmed
from discipline_framework.enforcement.hard_safety import enforce_hard_safety
from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.mt5_bridge.models import AccountSnapshot
from discipline_framework.rules.models import CheckResult

logger = logging.getLogger("discipline_framework.enforcement.active")


class ActiveEnforcer(Enforcer):
    mode_name = "active"

    def __init__(self, alerter, allow_live_execution: bool) -> None:
        require_live_execution_confirmed(allow_live_execution)
        super().__init__(alerter)

    def handle(
        self,
        results: list[CheckResult],
        bridge: MT5Bridge,
        snapshot: AccountSnapshot,
    ) -> None:
        for result in results:
            if result.passed:
                continue
            self.alerter.send_violation(result, self.mode_name)
            if enforce_hard_safety(result, bridge, self.mode_name):
                continue
            logger.info(
                "[active] %s: alerted, no auto-action defined yet (pending confirmed client rules)",
                result.rule_id,
            )
