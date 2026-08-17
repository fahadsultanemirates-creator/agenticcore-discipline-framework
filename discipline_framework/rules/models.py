"""Typed models for the trader's rules (config/rules.yaml) and for the
result of checking them against an account snapshot.

TradingRules and its sub-models mirror config/rules.yaml's structure
field-for-field — see that file for what each value means and which check
in engine.py consumes it. Using pydantic here means a typo or out-of-range
value in rules.yaml fails loudly at startup instead of silently
under/over-enforcing on a live account.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {Severity.INFO: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}[self]


class RiskRules(BaseModel):
    max_risk_per_trade_pct: float = Field(gt=0, le=100)
    max_daily_loss_pct: float = Field(gt=0, le=100)
    max_concurrent_positions: int = Field(gt=0)


class TargetRules(BaseModel):
    require_stop_loss: bool
    default_stop_loss_pips: float = Field(gt=0)
    require_take_profit: bool
    default_take_profit_pips: float = Field(gt=0)


class CooldownRules(BaseModel):
    consecutive_losses_trigger: int = Field(gt=0)
    cooldown_minutes: int = Field(gt=0)
    daily_loss_cooldown_minutes: int = Field(gt=0)


class SessionRules(BaseModel):
    allowed_symbols: list[str] = Field(min_length=1)
    trading_start_utc: str
    trading_end_utc: str
    max_trades_per_day: int = Field(gt=0)

    @field_validator("trading_start_utc", "trading_end_utc")
    @classmethod
    def _validate_hhmm(cls, value: str) -> str:
        hours, _, minutes = value.partition(":")
        if not (hours.isdigit() and minutes.isdigit()):
            raise ValueError(f"expected 'HH:MM', got {value!r}")
        h, m = int(hours), int(minutes)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"expected 'HH:MM' in range, got {value!r}")
        return value


class TradingRules(BaseModel):
    risk: RiskRules
    targets: TargetRules
    cooldown: CooldownRules
    session: SessionRules


class CheckResult(BaseModel):
    """The outcome of one rule check against one thing (a position, a
    trade, or the account as a whole) in one monitoring cycle."""

    rule_id: str
    passed: bool
    severity: Severity
    message: str
    # e.g. {"ticket": 123, "symbol": "EURUSD"} — kept loose so each check can
    # attach whatever's useful for alerting/logging without a shared schema.
    context: dict = Field(default_factory=dict)
