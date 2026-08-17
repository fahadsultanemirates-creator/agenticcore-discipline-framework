"""Enforcement modes: passive (alert-only), hybrid (hard-safety auto-acts),
active (broadest auto-action). See factory.py for mode selection and the
live-execution safety gate."""

from discipline_framework.enforcement.base import Enforcer, LiveExecutionNotConfirmed
from discipline_framework.enforcement.factory import build_enforcer
from discipline_framework.enforcement.pausable import PausableEnforcer

__all__ = ["Enforcer", "LiveExecutionNotConfirmed", "build_enforcer", "PausableEnforcer"]
