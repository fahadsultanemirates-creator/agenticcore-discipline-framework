"""Shared base for all three enforcement modes.

Scope note that applies to every mode, including active: this framework
never calls MT5Bridge.place_order() to originate a new trade. Its job is to
enforce the trader's exits and cutoffs on positions *he* opened — not to
decide when to get into the market. That line is intentional (see
README.md) and is enforced structurally: nothing in this package holds a
reference to place_order except the bridge interface itself.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from discipline_framework.alerts.telegram import Alerter
from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.mt5_bridge.models import AccountSnapshot
from discipline_framework.rules.models import CheckResult

LIVE_CONFIRM_ENV_VAR = "DISCIPLINE_FRAMEWORK_CONFIRM_LIVE"


class LiveExecutionNotConfirmed(RuntimeError):
    """Raised at startup when active/hybrid mode is selected without both
    required confirmations. See README.md's Safety posture section."""


def require_live_execution_confirmed(allow_live_execution: bool) -> None:
    env_confirmed = os.environ.get(LIVE_CONFIRM_ENV_VAR, "").strip().upper() == "YES"
    if allow_live_execution and env_confirmed:
        return
    raise LiveExecutionNotConfirmed(
        "This enforcement mode can place/modify/close real orders, which "
        "requires BOTH: enforcement.allow_live_execution: true in "
        f"config/settings.yaml AND the {LIVE_CONFIRM_ENV_VAR}=YES environment "
        "variable. Neither is enabled by default. Use passive mode until "
        "the client has explicitly signed off on live execution and "
        "config/rules.yaml holds his real numbers, not placeholders."
    )


class Enforcer(ABC):
    mode_name: str

    def __init__(self, alerter: Alerter) -> None:
        self.alerter = alerter

    @abstractmethod
    def handle(
        self,
        results: list[CheckResult],
        bridge: MT5Bridge,
        snapshot: AccountSnapshot,
    ) -> None:
        """React to one cycle's rule check results. Alert, act, or both,
        depending on mode."""
