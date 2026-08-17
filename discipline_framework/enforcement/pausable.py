"""Wraps any Enforcer with a live pause/resume toggle, controlled via the
Telegram /pause and /resume commands.

While paused, rule checks are still evaluated and logged every cycle (the
compliance log stays continuous — AccountWorker calls
ComplianceLogger.log_cycle before ever touching the enforcer), but no
alerts are sent and no actions are taken. That's "temporarily disable
enforcement without losing settings": the underlying rules and enforcement
mode are untouched, only whether this cycle's results get acted on.

Cross-process note: same reasoning as RulesStore.reload_if_stale() (see
rules/store.py) — in production an account's worker and the Telegram
command bot may run in different processes, so pause state is optionally
persisted to a small per-account JSON file (state_path) and re-read via
sync_from_disk() once per monitoring cycle. Without a state_path, this
behaves as pure in-memory in-process state, same as before multi-account
support.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from discipline_framework.enforcement.base import Enforcer
from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.mt5_bridge.models import AccountSnapshot
from discipline_framework.rules.models import CheckResult


class PausableEnforcer(Enforcer):
    def __init__(self, inner: Enforcer, state_path: Path | None = None) -> None:
        super().__init__(inner.alerter)
        self._inner = inner
        self._lock = threading.RLock()
        self._state_path = state_path
        self._enabled = _read_enabled(state_path) if state_path else True
        self._state_mtime = _mtime(state_path)

    @property
    def mode_name(self) -> str:
        return self._inner.mode_name

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def pause(self) -> None:
        self._set_enabled(False)

    def resume(self) -> None:
        self._set_enabled(True)

    def sync_from_disk(self) -> bool:
        """Re-reads pause state from state_path if it's changed since last
        checked. Call once per monitoring cycle. No-op (returns False) when
        state_path wasn't given."""
        if not self._state_path:
            return False
        with self._lock:
            mtime = _mtime(self._state_path)
            if mtime == self._state_mtime:
                return False
            self._enabled = _read_enabled(self._state_path)
            self._state_mtime = mtime
            return True

    def handle(
        self,
        results: list[CheckResult],
        bridge: MT5Bridge,
        snapshot: AccountSnapshot,
    ) -> None:
        if not self.enabled:
            return
        self._inner.handle(results, bridge, snapshot)

    def _set_enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = value
            self._persist()

    def _persist(self) -> None:
        if not self._state_path:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._state_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump({"paused": not self._enabled}, f)
        tmp_path.replace(self._state_path)  # atomic on POSIX
        self._state_mtime = _mtime(self._state_path)


def _read_enabled(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return not bool(data.get("paused", False))
    except (FileNotFoundError, ValueError):
        # Fail safe: an unreadable/corrupt state file should not silently
        # suppress enforcement.
        return True


def _mtime(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None
