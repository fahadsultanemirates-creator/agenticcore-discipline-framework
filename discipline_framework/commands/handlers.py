"""The actual logic behind each /command — kept separate from bot.py's
Telegram polling/transport so it can be unit tested without any network
access: build a CommandHandlers, call .dispatch("setrisk", ["1.5"]), and
check the returned string and the RulesStore's new state.

Every setter here goes through RulesStore, the same object RuleEngine reads
from — so a rule changed by /setrisk is enforced identically to one that
started out in config/rules.yaml. Nothing in the rule engine or enforcement
layer knows or cares which one it was.
"""

from __future__ import annotations

from pydantic import ValidationError

from discipline_framework.commands.errors import CommandError
from discipline_framework.enforcement.pausable import PausableEnforcer
from discipline_framework.rules.store import RulesStore

# Common forex session windows in UTC. These are widely-used approximations
# (not authoritative, and not the client's own hours) — a convenience for
# /setsession so he doesn't have to remember UTC offsets by heart. Prefer
# the explicit HH:MM-HH:MM form once his actual preferred hours are known.
SESSION_PRESETS: dict[str, tuple[str, str]] = {
    "asian": ("00:00", "09:00"),
    "tokyo": ("00:00", "09:00"),
    "london": ("07:00", "16:00"),
    "new_york": ("12:00", "21:00"),
    "newyork": ("12:00", "21:00"),
    "ny": ("12:00", "21:00"),
    "overlap": ("12:00", "16:00"),  # London/New York overlap — highest liquidity window
    "london_ny_overlap": ("12:00", "16:00"),
}

HELP_TEXT = """<b>Discipline framework — commands</b>

/setrisk &lt;percent&gt; — max risk per trade
/setdailyloss &lt;percent&gt; — max daily loss threshold
/setcooldown &lt;losses&gt; &lt;minutes&gt; — consecutive losses that trigger a cooldown, and its length
/setpairs &lt;symbol,symbol,...&gt; — symbol whitelist
/setsession &lt;HH:MM-HH:MM&gt; or a name (london, new_york, asian, overlap) — active trading hours (UTC)
/setmaxtrades &lt;number&gt; — max new trades per day
/status — show all currently active rule settings
/pause — disable enforcement without losing settings
/resume — re-enable enforcement
/help — this message"""


def _format_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first["loc"])
        return f"Invalid value for {field}: {first['msg']}"
    return str(exc)


def _parse_float(raw: str, usage: str) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise CommandError(usage) from None


def _parse_int(raw: str, usage: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise CommandError(usage) from None


class CommandHandlers:
    def __init__(self, rules_store: RulesStore, enforcer: PausableEnforcer) -> None:
        self.rules_store = rules_store
        self.enforcer = enforcer

    def dispatch(self, command: str, args: list[str]) -> str:
        handler = self.COMMANDS.get(command)
        if handler is None:
            return f"Unknown command: /{command}. Send /help for the list of commands."
        try:
            return handler(self, args)
        except (CommandError, ValidationError) as exc:
            return f"⚠️ {_format_error(exc)}"

    def _cmd_setrisk(self, args: list[str]) -> str:
        usage = "usage: /setrisk <percent>  e.g. /setrisk 1.5"
        if len(args) != 1:
            raise CommandError(usage)
        value = _parse_float(args[0], usage)
        rules = self.rules_store.set_max_risk_per_trade_pct(value)
        return f"✅ max risk per trade set to {rules.risk.max_risk_per_trade_pct}%"

    def _cmd_setdailyloss(self, args: list[str]) -> str:
        usage = "usage: /setdailyloss <percent>  e.g. /setdailyloss 5"
        if len(args) != 1:
            raise CommandError(usage)
        value = _parse_float(args[0], usage)
        rules = self.rules_store.set_max_daily_loss_pct(value)
        return f"✅ max daily loss set to {rules.risk.max_daily_loss_pct}%"

    def _cmd_setcooldown(self, args: list[str]) -> str:
        usage = "usage: /setcooldown <consecutive losses> <cooldown minutes>  e.g. /setcooldown 2 60"
        if len(args) != 2:
            raise CommandError(usage)
        losses = _parse_int(args[0], usage)
        minutes = _parse_int(args[1], usage)
        rules = self.rules_store.set_cooldown(losses, minutes)
        return (
            f"✅ cooldown set: {rules.cooldown.consecutive_losses_trigger} consecutive losses "
            f"→ {rules.cooldown.cooldown_minutes} min lockout"
        )

    def _cmd_setpairs(self, args: list[str]) -> str:
        usage = "usage: /setpairs <symbol,symbol,...>  e.g. /setpairs EURUSD,GBPUSD,USDJPY"
        if not args:
            raise CommandError(usage)
        symbols = [s.strip().upper() for s in " ".join(args).split(",") if s.strip()]
        if not symbols:
            raise CommandError(usage)
        rules = self.rules_store.set_allowed_symbols(symbols)
        return f"✅ allowed symbols set to: {', '.join(rules.session.allowed_symbols)}"

    def _cmd_setsession(self, args: list[str]) -> str:
        usage = (
            "usage: /setsession <HH:MM-HH:MM> (UTC) or a session name "
            f"({', '.join(sorted(SESSION_PRESETS))})"
        )
        if len(args) != 1:
            raise CommandError(usage)
        token = args[0].strip()
        if "-" in token and ":" in token:
            start, _, end = token.partition("-")
            start, end = start.strip(), end.strip()
        elif token.lower() in SESSION_PRESETS:
            start, end = SESSION_PRESETS[token.lower()]
        else:
            raise CommandError(usage)
        rules = self.rules_store.set_session(start, end)
        return f"✅ trading session set to {rules.session.trading_start_utc}-{rules.session.trading_end_utc} UTC"

    def _cmd_setmaxtrades(self, args: list[str]) -> str:
        usage = "usage: /setmaxtrades <number>  e.g. /setmaxtrades 5"
        if len(args) != 1:
            raise CommandError(usage)
        value = _parse_int(args[0], usage)
        rules = self.rules_store.set_max_trades_per_day(value)
        return f"✅ max trades per day set to {rules.session.max_trades_per_day}"

    def _cmd_status(self, args: list[str]) -> str:
        rules = self.rules_store.rules
        state = "▶️ ACTIVE" if self.enforcer.enabled else "⏸ PAUSED"
        lines = [
            f"<b>Enforcement:</b> {self.enforcer.mode_name} — {state}",
            "",
            f"Max risk/trade: {rules.risk.max_risk_per_trade_pct}%",
            f"Max daily loss: {rules.risk.max_daily_loss_pct}%",
            f"Max concurrent positions: {rules.risk.max_concurrent_positions}",
            f"Require stop-loss / take-profit: {rules.targets.require_stop_loss} / {rules.targets.require_take_profit}",
            f"Cooldown: {rules.cooldown.consecutive_losses_trigger} losses → "
            f"{rules.cooldown.cooldown_minutes} min lockout "
            f"(daily-loss lockout: {rules.cooldown.daily_loss_cooldown_minutes} min)",
            f"Allowed symbols: {', '.join(rules.session.allowed_symbols)}",
            f"Session: {rules.session.trading_start_utc}-{rules.session.trading_end_utc} UTC",
            f"Max trades/day: {rules.session.max_trades_per_day}",
        ]
        return "\n".join(lines)

    def _cmd_pause(self, args: list[str]) -> str:
        self.enforcer.pause()
        return (
            "⏸ Enforcement paused. Rules are still being checked and logged, "
            "but no alerts or actions will fire until /resume."
        )

    def _cmd_resume(self, args: list[str]) -> str:
        self.enforcer.resume()
        return "▶️ Enforcement resumed."

    def _cmd_help(self, args: list[str]) -> str:
        return HELP_TEXT

    COMMANDS = {
        "setrisk": _cmd_setrisk,
        "setdailyloss": _cmd_setdailyloss,
        "setcooldown": _cmd_setcooldown,
        "setpairs": _cmd_setpairs,
        "setsession": _cmd_setsession,
        "setmaxtrades": _cmd_setmaxtrades,
        "status": _cmd_status,
        "pause": _cmd_pause,
        "resume": _cmd_resume,
        "help": _cmd_help,
        "start": _cmd_help,
    }
