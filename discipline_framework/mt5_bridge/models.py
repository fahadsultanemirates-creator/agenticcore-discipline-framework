"""Domain models produced by an MT5Bridge and consumed by the RuleEngine.

These are intentionally independent of the MetaTrader5 package's own return
types (which are unnamed tuples) so the rest of the framework never touches
that SDK directly — only mt5_bridge/client.py does the translation. That
keeps the mock client and the real client interchangeable everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TradeDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class SymbolInfo:
    """Contract specs needed to translate a price distance into money risk."""

    symbol: str
    contract_size: float
    pip_size: float  # e.g. 0.0001 for EURUSD, 0.01 for USDJPY


@dataclass(frozen=True)
class Position:
    """An open position."""

    ticket: int
    symbol: str
    direction: TradeDirection
    volume: float  # lots
    open_price: float
    open_time: datetime
    stop_loss: float | None
    take_profit: float | None
    current_price: float
    profit: float  # floating P&L in account currency


@dataclass(frozen=True)
class Trade:
    """A closed trade (deal) from account history."""

    ticket: int
    symbol: str
    direction: TradeDirection
    volume: float
    open_time: datetime
    close_time: datetime
    profit: float  # realized P&L in account currency, net of swap/commission


@dataclass(frozen=True)
class AccountSnapshot:
    """Everything the RuleEngine needs to evaluate a single check cycle."""

    as_of: datetime
    balance: float
    equity: float
    open_positions: list[Position] = field(default_factory=list)
    closed_trades_today: list[Trade] = field(default_factory=list)
    symbol_info: dict[str, SymbolInfo] = field(default_factory=dict)
