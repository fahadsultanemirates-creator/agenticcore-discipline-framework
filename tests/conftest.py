from __future__ import annotations

from datetime import datetime, timezone

import pytest

from discipline_framework.mt5_bridge.mock_client import DEFAULT_SYMBOL_INFO
from discipline_framework.rules.models import (
    CooldownRules,
    RiskRules,
    SessionRules,
    TargetRules,
    TradingRules,
)

NOW = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)  # 10:00 UTC, inside the default session


@pytest.fixture
def rules() -> TradingRules:
    return TradingRules(
        risk=RiskRules(max_risk_per_trade_pct=2.0, max_daily_loss_pct=5.0, max_concurrent_positions=3),
        targets=TargetRules(
            require_stop_loss=True,
            default_stop_loss_pips=30,
            require_take_profit=True,
            default_take_profit_pips=60,
        ),
        cooldown=CooldownRules(
            consecutive_losses_trigger=2, cooldown_minutes=60, daily_loss_cooldown_minutes=1440
        ),
        session=SessionRules(
            allowed_symbols=["EURUSD", "GBPUSD", "USDJPY"],
            trading_start_utc="07:00",
            trading_end_utc="16:00",
            max_trades_per_day=5,
        ),
    )


@pytest.fixture
def symbol_info():
    return dict(DEFAULT_SYMBOL_INFO)
