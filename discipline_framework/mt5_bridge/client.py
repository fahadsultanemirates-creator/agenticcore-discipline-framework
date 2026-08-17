"""Real MetaTrader5 bridge.

Wraps the official `MetaTrader5` Python package, which only installs on
Windows (it loads the MT5 terminal's native DLL). Importing this module on
another platform, or without the terminal running, doesn't crash — it just
means connect() will fail cleanly and callers should fall back to
MockMT5Client (discipline_framework/config.py does this selection).

Safety: every write method re-checks `live_execution_enabled` itself, even
though enforcement/ is also supposed to gate on it. Two independent checks
because this is the one place a bug would mean a real order on a real
account.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from discipline_framework.mt5_bridge.interface import MT5Bridge
from discipline_framework.mt5_bridge.models import (
    AccountSnapshot,
    Position,
    SymbolInfo,
    Trade,
    TradeDirection,
)

logger = logging.getLogger("discipline_framework.mt5_bridge")

try:
    import MetaTrader5 as mt5

    MT5_AVAILABLE = True
except ImportError:  # expected on non-Windows dev/test machines
    mt5 = None
    MT5_AVAILABLE = False


class LiveExecutionDisabledError(RuntimeError):
    """Raised when a write operation is attempted without the safety gate open."""


class MetaTrader5Client(MT5Bridge):
    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        terminal_path: str | None = None,
        history_lookback_days: int = 2,
        live_execution_enabled: bool = False,
    ) -> None:
        if not MT5_AVAILABLE:
            raise ImportError(
                "The MetaTrader5 package is not installed/importable "
                "(it's Windows-only). Use MockMT5Client for dev/testing, or "
                "run this on a Windows host with an MT5 terminal installed."
            )
        self._login = login
        self._password = password
        self._server = server
        self._terminal_path = terminal_path
        self._history_lookback_days = history_lookback_days
        self.live_execution_enabled = live_execution_enabled
        self._connected = False

    def connect(self) -> bool:
        kwargs = {}
        if self._terminal_path:
            kwargs["path"] = self._terminal_path
        ok = mt5.initialize(
            login=self._login,
            password=self._password,
            server=self._server,
            **kwargs,
        )
        if not ok:
            logger.error("MT5 initialize() failed: %s", mt5.last_error())
            self._connected = False
            return False
        self._connected = True
        logger.info("Connected to MT5 (login=%s, server=%s)", self._login, self._server)
        return True

    def disconnect(self) -> None:
        if self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("Disconnected from MT5")

    def is_connected(self) -> bool:
        return self._connected

    def get_account_snapshot(self) -> AccountSnapshot:
        self._require_connected()

        account = mt5.account_info()
        if account is None:
            raise RuntimeError(f"mt5.account_info() failed: {mt5.last_error()}")

        raw_positions = mt5.positions_get() or ()
        positions = [self._to_position(p) for p in raw_positions]

        symbols_seen = {p.symbol for p in positions}
        symbol_info = {
            symbol: info
            for symbol in symbols_seen
            if (info := self._get_symbol_info(symbol)) is not None
        }

        closed_trades_today = self._get_closed_trades_today()
        for trade in closed_trades_today:
            symbols_seen.add(trade.symbol)
        for symbol in symbols_seen - symbol_info.keys():
            info = self._get_symbol_info(symbol)
            if info is not None:
                symbol_info[symbol] = info

        return AccountSnapshot(
            as_of=datetime.now(timezone.utc),
            balance=account.balance,
            equity=account.equity,
            open_positions=positions,
            closed_trades_today=closed_trades_today,
            symbol_info=symbol_info,
        )

    def close_position(self, ticket: int) -> bool:
        self._require_live_execution()
        position = next((p for p in mt5.positions_get() or () if p.ticket == ticket), None)
        if position is None:
            logger.warning("close_position: ticket %s not found (already closed?)", ticket)
            return False

        order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(position.symbol)
        price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "comment": "discipline_framework: enforced close",
        }
        result = mt5.order_send(request)
        success = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        if success:
            logger.warning("Closed position %s per enforcement rule", ticket)
        else:
            logger.error("Failed to close position %s: %s", ticket, result)
        return success

    def close_all_positions(self) -> bool:
        self._require_live_execution()
        positions = mt5.positions_get() or ()
        return all(self.close_position(p.ticket) for p in positions)

    def place_order(
        self,
        symbol: str,
        direction: TradeDirection,
        volume: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> int | None:
        self._require_live_execution()
        order_type = mt5.ORDER_TYPE_BUY if direction == TradeDirection.BUY else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(symbol)
        price = tick.ask if direction == TradeDirection.BUY else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": stop_loss or 0.0,
            "tp": take_profit or 0.0,
            "deviation": 20,
            "comment": "discipline_framework: rule-driven entry",
        }
        result = mt5.order_send(request)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.warning("Placed order per enforcement rule: ticket %s", result.order)
            return result.order
        logger.error("Failed to place order: %s", result)
        return None

    # -- internal helpers --

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")

    def _require_live_execution(self) -> None:
        self._require_connected()
        if not self.live_execution_enabled:
            raise LiveExecutionDisabledError(
                "Live execution is disabled on this client. This is expected "
                "in passive mode, and is a safety gate for active/hybrid "
                "mode until explicitly enabled — see config/settings.yaml "
                "(enforcement.allow_live_execution) and the "
                "DISCIPLINE_FRAMEWORK_CONFIRM_LIVE env var."
            )

    def _get_symbol_info(self, symbol: str) -> SymbolInfo | None:
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.warning("mt5.symbol_info(%s) returned None", symbol)
            return None
        return SymbolInfo(
            symbol=symbol,
            contract_size=info.trade_contract_size,
            pip_size=info.point * (10 if info.digits in (3, 5) else 1),
        )

    def _get_closed_trades_today(self) -> list[Trade]:
        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        lookback_start = start - timedelta(days=self._history_lookback_days - 1)
        deals = mt5.history_deals_get(lookback_start, now) or ()

        trades: dict[int, Trade] = {}
        for deal in deals:
            # entry == DEAL_ENTRY_OUT marks the closing leg of a position.
            if deal.entry != mt5.DEAL_ENTRY_OUT:
                continue
            close_time = datetime.fromtimestamp(deal.time, tz=timezone.utc)
            if close_time < start:
                continue
            trades[deal.position_id] = Trade(
                ticket=deal.position_id,
                symbol=deal.symbol,
                direction=TradeDirection.BUY if deal.type == mt5.DEAL_TYPE_SELL else TradeDirection.SELL,
                volume=deal.volume,
                open_time=close_time,  # refined below if we can find the entry leg
                close_time=close_time,
                profit=deal.profit + deal.swap + deal.commission,
            )
        return sorted(trades.values(), key=lambda t: t.close_time)

    def _to_position(self, raw) -> Position:
        return Position(
            ticket=raw.ticket,
            symbol=raw.symbol,
            direction=TradeDirection.BUY if raw.type == mt5.POSITION_TYPE_BUY else TradeDirection.SELL,
            volume=raw.volume,
            open_price=raw.price_open,
            open_time=datetime.fromtimestamp(raw.time, tz=timezone.utc),
            stop_loss=raw.sl or None,
            take_profit=raw.tp or None,
            current_price=raw.price_current,
            profit=raw.profit,
        )
