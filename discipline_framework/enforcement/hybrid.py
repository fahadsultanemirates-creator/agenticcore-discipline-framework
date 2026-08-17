"""Hybrid mode: auto-enforces only the hard safety rules (max daily loss
cutoff, cooldown lockout). Every other rule stays alert-only, permanently,
by design — not a placeholder pending more rules like in active mode.
Entries and any exit beyond the two hard cutoffs require the trader's own
manual confirmation.

Requires the live-execution safety gate (see base.py) to even construct,
same as active mode — closing a position is still a real order.
"""

from __future__ import annotations

from discipline_framework.enforcement.base import Enforcer, require_live_execution_confirmed
from discipline_framework.enforcement.hard_safety import enforce_hard_safety
from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.mt5_bridge.models import AccountSnapshot
from discipline_framework.rules.models import CheckResult


class HybridEnforcer(Enforcer):
    mode_name = "hybrid"

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
            enforce_hard_safety(result, bridge, self.mode_name)
