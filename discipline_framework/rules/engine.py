"""The RuleEngine: evaluates an AccountSnapshot against TradingRules.

Each `check_*` function is independent, takes (rules, snapshot), and
returns a list of CheckResult — one per thing it inspected (e.g. one per
open position), so a single cycle can report "3 positions compliant, 1
missing a stop-loss" rather than one pass/fail blob for the whole account.

Design note: checks only *read* the snapshot. They never touch the MT5
bridge directly — that separation is what makes RuleEngine trivially unit
testable (tests/test_rule_engine.py) and reusable unchanged across passive,
active, and hybrid enforcement modes. What to *do* about a failed check is
the enforcement layer's job, not this one's.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from discipline_framework.mt5_bridge.models import AccountSnapshot
from discipline_framework.rules.models import CheckResult, Severity, TradingRules
from discipline_framework.rules.store import RulesStore


def _parse_hhmm(value: str) -> time:
    hours, _, minutes = value.partition(":")
    return time(int(hours), int(minutes))


def _time_in_range(t: time, start: time, end: time) -> bool:
    """True if `t` falls in [start, end), handling ranges that wrap midnight."""
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def check_max_risk_per_trade(rules: TradingRules, snapshot: AccountSnapshot) -> list[CheckResult]:
    results = []
    for position in snapshot.open_positions:
        if position.stop_loss is None:
            continue  # covered separately by check_stop_loss_required
        info = snapshot.symbol_info.get(position.symbol)
        if info is None:
            continue  # can't size risk without contract specs; not a silent pass, just not this check's job

        # NOTE: assumes account currency == the pair's quote currency (true
        # for a USD account trading USD-quoted majors). Cross-currency
        # accounts need a conversion factor here — flag for refinement once
        # we know the client's account currency and instruments.
        stop_distance = abs(position.open_price - position.stop_loss)
        risk_amount = stop_distance * position.volume * info.contract_size
        risk_pct = (risk_amount / snapshot.equity) * 100 if snapshot.equity else 0.0
        passed = risk_pct <= rules.risk.max_risk_per_trade_pct

        results.append(
            CheckResult(
                rule_id="max_risk_per_trade",
                passed=passed,
                severity=Severity.INFO if passed else Severity.CRITICAL,
                message=(
                    f"{position.symbol} #{position.ticket}: risking {risk_pct:.2f}% "
                    f"of equity (limit {rules.risk.max_risk_per_trade_pct:.2f}%)"
                ),
                context={"ticket": position.ticket, "symbol": position.symbol, "risk_pct": risk_pct},
            )
        )
    return results


def check_stop_loss_required(rules: TradingRules, snapshot: AccountSnapshot) -> list[CheckResult]:
    if not rules.targets.require_stop_loss:
        return []
    results = []
    for position in snapshot.open_positions:
        passed = position.stop_loss is not None
        results.append(
            CheckResult(
                rule_id="stop_loss_required",
                passed=passed,
                severity=Severity.INFO if passed else Severity.CRITICAL,
                message=f"{position.symbol} #{position.ticket}: "
                + ("stop-loss set" if passed else "NO STOP-LOSS SET"),
                context={"ticket": position.ticket, "symbol": position.symbol},
            )
        )
    return results


def check_take_profit_required(rules: TradingRules, snapshot: AccountSnapshot) -> list[CheckResult]:
    if not rules.targets.require_take_profit:
        return []
    results = []
    for position in snapshot.open_positions:
        passed = position.take_profit is not None
        results.append(
            CheckResult(
                rule_id="take_profit_required",
                passed=passed,
                severity=Severity.INFO if passed else Severity.WARNING,
                message=f"{position.symbol} #{position.ticket}: "
                + ("take-profit set" if passed else "no take-profit set — no defined exit target"),
                context={"ticket": position.ticket, "symbol": position.symbol},
            )
        )
    return results


def check_max_concurrent_positions(rules: TradingRules, snapshot: AccountSnapshot) -> list[CheckResult]:
    count = len(snapshot.open_positions)
    passed = count <= rules.risk.max_concurrent_positions
    return [
        CheckResult(
            rule_id="max_concurrent_positions",
            passed=passed,
            severity=Severity.INFO if passed else Severity.WARNING,
            message=f"{count} open position(s) (limit {rules.risk.max_concurrent_positions})",
            context={"count": count},
        )
    ]


def check_allowed_symbols(rules: TradingRules, snapshot: AccountSnapshot) -> list[CheckResult]:
    allowed = set(rules.session.allowed_symbols)
    results = []
    for position in snapshot.open_positions:
        passed = position.symbol in allowed
        results.append(
            CheckResult(
                rule_id="allowed_symbol",
                passed=passed,
                severity=Severity.INFO if passed else Severity.WARNING,
                message=f"{position.symbol} #{position.ticket}: "
                + ("allowed symbol" if passed else "symbol not in the approved list"),
                context={"ticket": position.ticket, "symbol": position.symbol},
            )
        )
    return results


def check_trading_session(rules: TradingRules, snapshot: AccountSnapshot) -> list[CheckResult]:
    start = _parse_hhmm(rules.session.trading_start_utc)
    end = _parse_hhmm(rules.session.trading_end_utc)
    results = []
    for position in snapshot.open_positions:
        opened_at = position.open_time.astimezone(timezone.utc).time()
        passed = _time_in_range(opened_at, start, end)
        results.append(
            CheckResult(
                rule_id="trading_session",
                passed=passed,
                severity=Severity.INFO if passed else Severity.WARNING,
                message=(
                    f"{position.symbol} #{position.ticket}: opened at {opened_at.strftime('%H:%M')} UTC "
                    f"({'within' if passed else 'outside'} session {rules.session.trading_start_utc}-"
                    f"{rules.session.trading_end_utc} UTC)"
                ),
                context={"ticket": position.ticket, "symbol": position.symbol},
            )
        )
    return results


def check_max_trades_per_day(rules: TradingRules, snapshot: AccountSnapshot) -> list[CheckResult]:
    today = snapshot.as_of.astimezone(timezone.utc).date()
    opened_today = sum(
        1 for p in snapshot.open_positions if p.open_time.astimezone(timezone.utc).date() == today
    )
    count = opened_today + len(snapshot.closed_trades_today)
    passed = count <= rules.session.max_trades_per_day
    return [
        CheckResult(
            rule_id="max_trades_per_day",
            passed=passed,
            severity=Severity.INFO if passed else Severity.WARNING,
            message=f"{count} trade(s) opened today (limit {rules.session.max_trades_per_day})",
            context={"count": count},
        )
    ]


def check_consecutive_loss_cooldown(rules: TradingRules, snapshot: AccountSnapshot) -> list[CheckResult]:
    trades = sorted(snapshot.closed_trades_today, key=lambda t: t.close_time)
    if not trades:
        return []

    consecutive_losses = 0
    last_loss_close_time = None
    for trade in reversed(trades):
        if trade.profit < 0:
            consecutive_losses += 1
            last_loss_close_time = last_loss_close_time or trade.close_time
        else:
            break

    if consecutive_losses < rules.cooldown.consecutive_losses_trigger:
        return []

    cooldown_end = last_loss_close_time + timedelta(minutes=rules.cooldown.cooldown_minutes)
    if snapshot.as_of >= cooldown_end:
        return [
            CheckResult(
                rule_id="consecutive_loss_cooldown",
                passed=True,
                severity=Severity.INFO,
                message=f"{consecutive_losses} consecutive losses today; cooldown window has elapsed",
                context={"consecutive_losses": consecutive_losses},
            )
        ]

    violating = [p for p in snapshot.open_positions if p.open_time > last_loss_close_time]
    if not violating:
        return [
            CheckResult(
                rule_id="consecutive_loss_cooldown",
                passed=True,
                severity=Severity.INFO,
                message=(
                    f"Cooldown active after {consecutive_losses} consecutive losses "
                    f"(ends {cooldown_end.isoformat()}); no new trades opened"
                ),
                context={"consecutive_losses": consecutive_losses, "cooldown_end": cooldown_end.isoformat()},
            )
        ]

    return [
        CheckResult(
            rule_id="consecutive_loss_cooldown",
            passed=False,
            severity=Severity.CRITICAL,
            message=(
                f"{p.symbol} #{p.ticket}: opened during mandatory cooldown after "
                f"{consecutive_losses} consecutive losses (cooldown ends {cooldown_end.isoformat()})"
            ),
            context={
                "ticket": p.ticket,
                "symbol": p.symbol,
                "consecutive_losses": consecutive_losses,
                "cooldown_end": cooldown_end.isoformat(),
            },
        )
        for p in violating
    ]


def check_max_daily_loss(rules: TradingRules, snapshot: AccountSnapshot) -> list[CheckResult]:
    if snapshot.balance <= 0:
        return []

    # Simplification: measures loss against current balance rather than the
    # day's opening balance (we don't have that without persisting state
    # across cycles). Close enough for alerting; revisit if the client wants
    # this precise to the cent.
    daily_pnl = sum(t.profit for t in snapshot.closed_trades_today) + sum(
        p.profit for p in snapshot.open_positions
    )
    loss_pct = max(0.0, -daily_pnl) / snapshot.balance * 100
    breached = loss_pct >= rules.risk.max_daily_loss_pct

    if not breached:
        return [
            CheckResult(
                rule_id="max_daily_loss",
                passed=True,
                severity=Severity.INFO,
                message=f"Daily loss {loss_pct:.2f}% within limit ({rules.risk.max_daily_loss_pct:.2f}%)",
                context={"loss_pct": loss_pct},
            )
        ]

    results = [
        CheckResult(
            rule_id="max_daily_loss",
            passed=False,
            severity=Severity.CRITICAL,
            message=(
                f"MAX DAILY LOSS BREACHED: {loss_pct:.2f}% >= {rules.risk.max_daily_loss_pct:.2f}% "
                "— trading should stop for the day"
            ),
            context={"loss_pct": loss_pct},
        )
    ]
    if snapshot.open_positions:
        results.append(
            CheckResult(
                rule_id="max_daily_loss_open_positions",
                passed=False,
                severity=Severity.CRITICAL,
                message=f"{len(snapshot.open_positions)} position(s) still open after max daily loss breach",
                context={"count": len(snapshot.open_positions)},
            )
        )
    return results


# Every check the engine runs, in a stable, readable order. Add new checks
# here (and give them a distinct rule_id above) — nothing else needs to
# change to pick them up.
DEFAULT_CHECKS = [
    check_max_daily_loss,
    check_consecutive_loss_cooldown,
    check_max_risk_per_trade,
    check_stop_loss_required,
    check_take_profit_required,
    check_max_concurrent_positions,
    check_allowed_symbols,
    check_trading_session,
    check_max_trades_per_day,
]


class RuleEngine:
    """Evaluates against whatever TradingRules a RulesStore currently holds.

    Accepts either a RulesStore directly (the live case: main.py shares one
    store between this engine and the Telegram command interface, so a
    mid-session /setrisk takes effect on the very next cycle) or a plain
    TradingRules (the static case: tests, or any caller that doesn't need
    live updates), which is wrapped in a private, non-persisting RulesStore.
    """

    def __init__(self, rules: TradingRules | RulesStore, checks=None) -> None:
        self._store = rules if isinstance(rules, RulesStore) else RulesStore(rules)
        self._checks = list(checks) if checks is not None else list(DEFAULT_CHECKS)

    @property
    def rules(self) -> TradingRules:
        return self._store.rules

    def evaluate(self, snapshot: AccountSnapshot) -> list[CheckResult]:
        rules = self.rules
        results: list[CheckResult] = []
        for check in self._checks:
            results.extend(check(rules, snapshot))
        return results
