"""MetaTrader 5 connectivity: a bridge interface plus real + mock clients."""

from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.mt5_bridge.models import (
    AccountSnapshot,
    Position,
    SymbolInfo,
    Trade,
    TradeDirection,
)

__all__ = [
    "MT5Bridge",
    "AccountSnapshot",
    "Position",
    "SymbolInfo",
    "Trade",
    "TradeDirection",
]
