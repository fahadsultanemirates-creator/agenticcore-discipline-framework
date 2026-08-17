# Enforcement modes

Set via `enforcement.mode` in `config/settings.yaml`. One of `passive`,
`hybrid`, `active`.

## passive (default)

Monitors the account every `monitoring.poll_interval_seconds` and sends a
Telegram alert for every rule violation. Never calls any MT5 write
operation (`place_order`, `close_position`, `close_all_positions`). This is
the only mode enabled without further configuration, and the only one
that's safe to point at a live account before the client's exact rule
numbers are confirmed.

## hybrid

Everything passive mode does, plus: auto-closes positions when one of the
two **hard safety rules** is violated —

- `max_daily_loss` / `max_daily_loss_open_positions`: closes **all** open
  positions when the day's realized + floating loss breaches
  `risk.max_daily_loss_pct`.
- `consecutive_loss_cooldown`: closes any position opened **during** the
  mandatory cooldown window that follows
  `cooldown.consecutive_losses_trigger` consecutive losing trades.

Every other rule (missing stop-loss, oversized risk, wrong symbol/session,
too many trades today) is alert-only, permanently, by design — hybrid mode
never auto-adjusts an entry or exit beyond the two cutoffs above. That
scope is intentional, not a placeholder.

## active

Same hard-safety auto-actions as hybrid today. The mode exists separately
because it's where broader auto-enforcement (e.g. auto-closing a position
that's missing a required stop-loss) would go once the client's exact
numeric rules are confirmed and we've agreed with him on what "auto-act"
should mean for each one — see the TODO in
`discipline_framework/enforcement/active.py`. Until then, active and hybrid
behave identically.

Neither mode ever calls `place_order` — this framework enforces exits and
cutoffs on trades the client already opened, it does not originate trades.
See `discipline_framework/enforcement/base.py`.

## The live-execution safety gate

`hybrid` and `active` refuse to construct unless **both** of these are true:

1. `enforcement.allow_live_execution: true` in `config/settings.yaml`
2. The environment variable `DISCIPLINE_FRAMEWORK_CONFIRM_LIVE=YES`

Missing either raises `LiveExecutionNotConfirmed` at startup, before any
connection to MT5 is made. This is a deliberate double confirmation: one
lives in a file that's easy to review/diff, the other is an explicit,
session-scoped opt-in that isn't persisted anywhere by default.

The concrete MT5 client (`MetaTrader5Client`) *also* independently checks a
`live_execution_enabled` flag before any write call, so a bug in the
enforcement layer alone can't cause a live order — see
`discipline_framework/mt5_bridge/client.py`.

## Recommended rollout

1. **Passive + mock bridge** (`--mock`) — validate the pipeline end-to-end
   with no MT5 terminal at all.
2. **Passive + real MT5, demo account** — validate real data flows through
   correctly; alerts should match what you'd expect from your own trade
   history.
3. **Passive + real MT5, live account** — once `config/rules.yaml` holds
   the client's actual numbers, run passive for a while and compare its
   alerts against his own sense of when he broke a rule.
4. **Hybrid** — only after the client has explicitly asked for the hard
   safety cutoffs to be automatic, and only on a demo account first.
5. **Active** — revisit once hybrid has a track record and the client wants
   more automated beyond the two hard cutoffs.
