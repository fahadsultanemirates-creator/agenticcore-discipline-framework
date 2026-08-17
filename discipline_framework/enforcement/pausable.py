"""Wraps any Enforcer with a live pause/resume toggle, controlled via the
Telegram /pause and /resume commands.

While paused, rule checks are still evaluated and logged every cycle (the
compliance log stays continuous — main.py calls ComplianceLogger.log_cycle
before ever touching the enforcer), but no alerts are sent and no actions
are taken. That's "temporarily disable enforcement without losing
settings": the underlying rules and enforcement mode are untouched, only
whether this cycle's results get acted on.
"""

from __future__ import annotations

import threading

from discipline_framework.enforcement.base import Enforcer
from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.mt5_bridge.models import AccountSnapshot
from discipline_framework.rules.models import CheckResult


class PausableEnforcer(Enforcer):
    def __init__(self, inner: Enforcer) -> None:
        super().__init__(inner.alerter)
        self._inner = inner
        self._lock = threading.RLock()
        self._enabled = True

    @property
    def mode_name(self) -> str:
        return self._inner.mode_name

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def pause(self) -> None:
        with self._lock:
            self._enabled = False

    def resume(self) -> None:
        with self._lock:
            self._enabled = True

    def handle(
        self,
        results: list[CheckResult],
        bridge: MT5Bridge,
        snapshot: AccountSnapshot,
    ) -> None:
        if not self.enabled:
            return
        self._inner.handle(results, bridge, snapshot)
