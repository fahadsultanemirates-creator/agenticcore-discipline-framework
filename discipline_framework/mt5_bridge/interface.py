"""Abstract MT5 bridge interface.

Everything above this layer (rule engine, enforcement, main loop) depends
only on this interface, never on the concrete client. That's what lets
MockMT5Client stand in for the real terminal in dev/tests, and it's what
would let us swap in a different broker's SDK later without touching
anything else.

Read vs. write split: get_account_snapshot() is the only method the
`passive` enforcement mode ever calls. close_position() / place_order() /
modify_position() exist for `active`/`hybrid` mode and are expected to raise
if the concrete implementation hasn't been explicitly unlocked for live
execution (see discipline_framework/enforcement/ and config.py's
allow_live_execution gate).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from discipline_framework.mt5_bridge.models import AccountSnapshot, TradeDirection


class MT5Bridge(ABC):
    @abstractmethod
    def connect(self) -> bool:
        """Establish the connection. Returns True on success."""

    @abstractmethod
    def disconnect(self) -> None:
        """Tear down the connection."""

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    def get_account_snapshot(self) -> AccountSnapshot:
        """Read current account state: balance, equity, open positions, and
        today's closed trades. Read-only — safe to call in any enforcement
        mode."""

    # -- Write operations. Only ever called by active/hybrid enforcers, and
    # only after those enforcers have confirmed the live-execution gate is
    # open. Real implementations MUST re-check that gate themselves rather
    # than trusting the caller — see mt5_bridge/client.py.

    @abstractmethod
    def close_position(self, ticket: int) -> bool:
        """Close a single open position at market."""

    @abstractmethod
    def close_all_positions(self) -> bool:
        """Close every open position at market (the hard safety cutoff)."""

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        direction: TradeDirection,
        volume: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> int | None:
        """Place a market order. Returns the resulting ticket, or None on
        failure."""
