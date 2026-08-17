"""In-memory mock MT5 bridge.

Lets the full pipeline (rule engine -> enforcement -> alerts -> logging)
run end-to-end on any OS, without a live MT5 terminal, for local dev,
demos, and the test suite. Seed it with whatever positions/trades/balance
you want to exercise a given rule check.

Write methods (close_position, place_order, ...) mutate the in-memory state
and always succeed unless live_execution_enabled is False and the safety
gate rejects the call — mirroring the real client's guard so enforcement
code paths behave identically against both.
"""

from __future__ import annotations

from datetime import datetime, timezone

from discipline_framework.mt5_bridge.client import LiveExecutionDisabledError
from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.mt5_bridge.models import (
    AccountSnapshot,
    Position,
    SymbolInfo,
    Trade,
    TradeDirection,
)

DEFAULT_SYMBOL_INFO = {
    "EURUSD": SymbolInfo(symbol="EURUSD", contract_size=100_000, pip_size=0.0001),
    "GBPUSD": SymbolInfo(symbol="GBPUSD", contract_size=100_000, pip_size=0.0001),
    "USDJPY": SymbolInfo(symbol="USDJPY", contract_size=100_000, pip_size=0.01),
}


class MockMT5Client(MT5Bridge):
    def __init__(
        self,
        balance: float = 10_000.0,
        equity: float | None = None,
        open_positions: list[Position] | None = None,
        closed_trades_today: list[Trade] | None = None,
        symbol_info: dict[str, SymbolInfo] | None = None,
        live_execution_enabled: bool = False,
    ) -> None:
        self.balance = balance
        self.equity = equity if equity is not None else balance
        self.open_positions: list[Position] = list(open_positions or [])
        self.closed_trades_today: list[Trade] = list(closed_trades_today or [])
        self.symbol_info = dict(symbol_info or DEFAULT_SYMBOL_INFO)
        self.live_execution_enabled = live_execution_enabled
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_account_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            as_of=datetime.now(timezone.utc),
            balance=self.balance,
            equity=self.equity,
            open_positions=list(self.open_positions),
            closed_trades_today=list(self.closed_trades_today),
            symbol_info=dict(self.symbol_info),
        )

    def close_position(self, ticket: int) -> bool:
        self._require_live_execution()
        position = next((p for p in self.open_positions if p.ticket == ticket), None)
        if position is None:
            return False
        self.open_positions = [p for p in self.open_positions if p.ticket != ticket]
        self.closed_trades_today.append(
            Trade(
                ticket=position.ticket,
                symbol=position.symbol,
                direction=position.direction,
                volume=position.volume,
                open_time=position.open_time,
                close_time=datetime.now(timezone.utc),
                profit=position.profit,
            )
        )
        return True

    def close_all_positions(self) -> bool:
        self._require_live_execution()
        return all(self.close_position(p.ticket) for p in list(self.open_positions))

    def place_order(
        self,
        symbol: str,
        direction: TradeDirection,
        volume: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> int | None:
        self._require_live_execution()
        ticket = max((p.ticket for p in self.open_positions), default=0) + 1
        self.open_positions.append(
            Position(
                ticket=ticket,
                symbol=symbol,
                direction=direction,
                volume=volume,
                open_price=0.0,
                open_time=datetime.now(timezone.utc),
                stop_loss=stop_loss,
                take_profit=take_profit,
                current_price=0.0,
                profit=0.0,
            )
        )
        return ticket

    def _require_live_execution(self) -> None:
        if not self.live_execution_enabled:
            raise LiveExecutionDisabledError(
                "Live execution is disabled on this mock client (mirrors the "
                "real client's safety gate)."
            )
