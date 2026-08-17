"""The actual logic behind each /command — kept separate from bot.py's
Telegram polling/transport so it can be unit tested without any network
access: build a CommandHandlers, call .dispatch("setrisk", ["account_1", "1.5"]),
and check the returned string and the right account's RulesStore state.

Every /set* command takes an account_id as its first argument and resolves
it to that account's AccountRuntime (discipline_framework/accounts.py) —
one Telegram bot manages every account, but a command only ever touches the
one account it names. /status, /pause, and /resume additionally accept
"all" to act on (or report) every account at once.

Every setter goes through that account's RulesStore, the same object its
AccountWorker reads from — so a rule changed by /setrisk is enforced
identically to one that started out in that account's rules.yaml. Nothing
in the rule engine or enforcement layer knows or cares which one it was.
"""

from __future__ import annotations

from pydantic import ValidationError

from discipline_framework.accounts import AccountRuntime
from discipline_framework.commands.errors import CommandError

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
Most commands take an account id first — see /accounts for the list.

/accounts — list every account this bot manages
/setrisk &lt;account_id&gt; &lt;percent&gt; — max risk per trade
/setdailyloss &lt;account_id&gt; &lt;percent&gt; — max daily loss threshold
/setcooldown &lt;account_id&gt; &lt;losses&gt; &lt;minutes&gt; — consecutive losses that trigger a cooldown, and its length
/setpairs &lt;account_id&gt; &lt;symbol,symbol,...&gt; — symbol whitelist
/setsession &lt;account_id&gt; &lt;HH:MM-HH:MM&gt; or a name (london, new_york, asian, overlap) — active trading hours (UTC)
/setmaxtrades &lt;account_id&gt; &lt;number&gt; — max new trades per day
/status &lt;account_id&gt; or /status all — show currently active rule settings
/pause &lt;account_id&gt; or /pause all — disable enforcement without losing settings
/resume &lt;account_id&gt; or /resume all — re-enable enforcement
/help — this message"""


def _format_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first["loc"])
        return f"Invalid value for {field}: {first['msg']}"
    return str(exc)


def _parse_float(raw: str, usage: str) -> float:
    try:
        return float(raw.strip().rstrip("%"))
    except (TypeError, ValueError):
        raise CommandError(usage) from None


def _parse_int(raw: str, usage: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise CommandError(usage) from None


class CommandHandlers:
    def __init__(self, accounts: dict[str, AccountRuntime]) -> None:
        # account_id -> AccountRuntime, in config/accounts.yaml order.
        # Only accounts this process is actually running — never a disabled
        # or unreachable one, since those never got an AccountRuntime built.
        self.accounts = accounts

    def dispatch(self, command: str, args: list[str]) -> str:
        handler = self.COMMANDS.get(command)
        if handler is None:
            return f"Unknown command: /{command}. Send /help for the list of commands."
        try:
            return handler(self, args)
        except (CommandError, ValidationError) as exc:
            return f"⚠️ {_format_error(exc)}"

    def _resolve(self, account_id: str) -> AccountRuntime:
        runtime = self.accounts.get(account_id)
        if runtime is None:
            known = ", ".join(self.accounts) or "(none configured)"
            raise CommandError(f"unknown account '{account_id}'. Known accounts: {known}")
        return runtime

    def _resolve_many(self, token: str) -> list[AccountRuntime]:
        if token.lower() == "all":
            return list(self.accounts.values())
        return [self._resolve(token)]

    def _cmd_accounts(self, args: list[str]) -> str:
        if not self.accounts:
            return "No accounts are currently running."
        lines = ["<b>Accounts</b>", ""]
        for runtime in self.accounts.values():
            state = "▶️" if runtime.enforcer.enabled else "⏸"
            lines.append(
                f"{state} <b>{runtime.account.id}</b> — {runtime.account.label} "
                f"({runtime.enforcer.mode_name})"
            )
        return "\n".join(lines)

    def _cmd_setrisk(self, args: list[str]) -> str:
        usage = "usage: /setrisk <account_id> <percent>  e.g. /setrisk account_1 1.5"
        if len(args) != 2:
            raise CommandError(usage)
        runtime = self._resolve(args[0])
        value = _parse_float(args[1], usage)
        rules = runtime.rules_store.set_max_risk_per_trade_pct(value)
        return f"✅ [{runtime.account.id}] max risk per trade set to {rules.risk.max_risk_per_trade_pct}%"

    def _cmd_setdailyloss(self, args: list[str]) -> str:
        usage = "usage: /setdailyloss <account_id> <percent>  e.g. /setdailyloss account_1 5"
        if len(args) != 2:
            raise CommandError(usage)
        runtime = self._resolve(args[0])
        value = _parse_float(args[1], usage)
        rules = runtime.rules_store.set_max_daily_loss_pct(value)
        return f"✅ [{runtime.account.id}] max daily loss set to {rules.risk.max_daily_loss_pct}%"

    def _cmd_setcooldown(self, args: list[str]) -> str:
        usage = (
            "usage: /setcooldown <account_id> <consecutive losses> <cooldown minutes>  "
            "e.g. /setcooldown account_1 2 60"
        )
        if len(args) != 3:
            raise CommandError(usage)
        runtime = self._resolve(args[0])
        losses = _parse_int(args[1], usage)
        minutes = _parse_int(args[2], usage)
        rules = runtime.rules_store.set_cooldown(losses, minutes)
        return (
            f"✅ [{runtime.account.id}] cooldown set: {rules.cooldown.consecutive_losses_trigger} "
            f"consecutive losses → {rules.cooldown.cooldown_minutes} min lockout"
        )

    def _cmd_setpairs(self, args: list[str]) -> str:
        usage = "usage: /setpairs <account_id> <symbol,symbol,...>  e.g. /setpairs account_1 EURUSD,GBPUSD,USDJPY"
        if len(args) < 2:
            raise CommandError(usage)
        runtime = self._resolve(args[0])
        symbols = [s.strip().upper() for s in " ".join(args[1:]).split(",") if s.strip()]
        if not symbols:
            raise CommandError(usage)
        rules = runtime.rules_store.set_allowed_symbols(symbols)
        return f"✅ [{runtime.account.id}] allowed symbols set to: {', '.join(rules.session.allowed_symbols)}"

    def _cmd_setsession(self, args: list[str]) -> str:
        usage = (
            "usage: /setsession <account_id> <HH:MM-HH:MM> (UTC) or a session name "
            f"({', '.join(sorted(SESSION_PRESETS))})"
        )
        if len(args) != 2:
            raise CommandError(usage)
        runtime = self._resolve(args[0])
        token = args[1].strip()
        if "-" in token and ":" in token:
            start, _, end = token.partition("-")
            start, end = start.strip(), end.strip()
        elif token.lower() in SESSION_PRESETS:
            start, end = SESSION_PRESETS[token.lower()]
        else:
            raise CommandError(usage)
        rules = runtime.rules_store.set_session(start, end)
        return (
            f"✅ [{runtime.account.id}] trading session set to "
            f"{rules.session.trading_start_utc}-{rules.session.trading_end_utc} UTC"
        )

    def _cmd_setmaxtrades(self, args: list[str]) -> str:
        usage = "usage: /setmaxtrades <account_id> <number>  e.g. /setmaxtrades account_1 5"
        if len(args) != 2:
            raise CommandError(usage)
        runtime = self._resolve(args[0])
        value = _parse_int(args[1], usage)
        rules = runtime.rules_store.set_max_trades_per_day(value)
        return f"✅ [{runtime.account.id}] max trades per day set to {rules.session.max_trades_per_day}"

    def _cmd_status(self, args: list[str]) -> str:
        usage = "usage: /status <account_id>  or  /status all"
        if len(args) != 1:
            raise CommandError(usage)
        runtimes = self._resolve_many(args[0])
        return "\n\n".join(self._status_text(r) for r in runtimes)

    def _status_text(self, runtime: AccountRuntime) -> str:
        rules = runtime.rules_store.rules
        state = "▶️ ACTIVE" if runtime.enforcer.enabled else "⏸ PAUSED"
        lines = [
            f"<b>{runtime.account.id}</b> ({runtime.account.label})",
            f"Enforcement: {runtime.enforcer.mode_name} — {state}",
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
        usage = "usage: /pause <account_id>  or  /pause all"
        if len(args) != 1:
            raise CommandError(usage)
        runtimes = self._resolve_many(args[0])
        for runtime in runtimes:
            runtime.enforcer.pause()
        target = "all accounts" if args[0].lower() == "all" else runtimes[0].account.id
        return (
            f"⏸ Enforcement paused for {target}. Rules are still being checked and logged, "
            "but no alerts or actions will fire until /resume."
        )

    def _cmd_resume(self, args: list[str]) -> str:
        usage = "usage: /resume <account_id>  or  /resume all"
        if len(args) != 1:
            raise CommandError(usage)
        runtimes = self._resolve_many(args[0])
        for runtime in runtimes:
            runtime.enforcer.resume()
        target = "all accounts" if args[0].lower() == "all" else runtimes[0].account.id
        return f"▶️ Enforcement resumed for {target}."

    def _cmd_help(self, args: list[str]) -> str:
        return HELP_TEXT

    COMMANDS = {
        "accounts": _cmd_accounts,
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
