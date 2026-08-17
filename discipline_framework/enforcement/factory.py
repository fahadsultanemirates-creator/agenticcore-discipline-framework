"""Selects an Enforcer by mode name. The one place that translates
config/settings.yaml's `enforcement.mode` string into a concrete class."""

from __future__ import annotations

from discipline_framework.alerts.telegram import Alerter
from discipline_framework.enforcement.active import ActiveEnforcer
from discipline_framework.enforcement.base import Enforcer
from discipline_framework.enforcement.hybrid import HybridEnforcer
from discipline_framework.enforcement.passive import PassiveEnforcer

_MODES = {
    "passive": PassiveEnforcer,
    "active": ActiveEnforcer,
    "hybrid": HybridEnforcer,
}


def build_enforcer(mode: str, alerter: Alerter, allow_live_execution: bool) -> Enforcer:
    try:
        enforcer_cls = _MODES[mode]
    except KeyError:
        raise ValueError(f"Unknown enforcement mode {mode!r}; expected one of {sorted(_MODES)}") from None

    if enforcer_cls is PassiveEnforcer:
        return enforcer_cls(alerter)
    return enforcer_cls(alerter, allow_live_execution=allow_live_execution)
