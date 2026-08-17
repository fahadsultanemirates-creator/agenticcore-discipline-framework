"""Passive mode: observe and alert. Never touches the account.

This is the default mode and the only one enabled without extra
confirmation — see config/settings.yaml and README.md.
"""

from __future__ import annotations

import logging

from discipline_framework.enforcement.base import Enforcer
from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.mt5_bridge.models import AccountSnapshot
from discipline_framework.rules.models import CheckResult

logger = logging.getLogger("discipline_framework.enforcement.passive")


class PassiveEnforcer(Enforcer):
    mode_name = "passive"

    def handle(
        self,
        results: list[CheckResult],
        bridge: MT5Bridge,
        snapshot: AccountSnapshot,
    ) -> None:
        for result in results:
            if result.passed:
                continue
            logger.warning("[%s] %s: %s", result.severity.value, result.rule_id, result.message)
            self.alerter.send_violation(result, self.mode_name)
