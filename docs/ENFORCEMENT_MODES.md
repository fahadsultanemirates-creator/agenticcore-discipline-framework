# Enforcement modes

Set **per account**, via `enforcement.mode` in that account's entry in
`config/accounts.yaml`. One of `passive`, `hybrid`, `active` — see
[`docs/MULTI_ACCOUNT.md`](MULTI_ACCOUNT.md) for why this is per-account
rather than a single global setting (different accounts can run different
risk postures) and for how the safety gate below still applies deployment-wide.

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

`hybrid` and `active` refuse to construct for a given account unless
**both** of these are true:

1. That account's `enforcement.allow_live_execution: true` in
   `config/accounts.yaml` — a **per-account** switch.
2. The environment variable `DISCIPLINE_FRAMEWORK_CONFIRM_LIVE=YES` — a
   single **deployment-wide** switch, not per-account.

Missing either raises `LiveExecutionNotConfirmed` at startup, before any
connection to MT5 is made, for that account only — other accounts are
unaffected. This is a deliberate two-layer confirmation:
`allow_live_execution` says "this specific account is cleared for live
execution"; `DISCIPLINE_FRAMEWORK_CONFIRM_LIVE` says "this deployment is
allowed to place live orders at all." Requiring both means turning on live
trading for a new account is one YAML line, reviewable in a diff, but can
never take effect unless someone has also deliberately set the environment
variable on that specific machine/session — an operator can't accidentally
ship a config change that goes live by itself.

The concrete MT5 client (`MetaTrader5Client`) *also* independently checks a
`live_execution_enabled` flag before any write call, so a bug in the
enforcement layer alone can't cause a live order — see
`discipline_framework/mt5_bridge/client.py`.

## Recommended rollout

1. **Passive + mock bridge** (`--mock`) — validate the pipeline end-to-end
   with no MT5 terminal at all.
2. **Passive + real MT5, demo account(s)** — validate real data flows
   through correctly; alerts should match what you'd expect from your own
   trade history, for every account.
3. **Passive + real MT5, live accounts** — once each account's
   `config/rules/<account_id>.yaml` holds the client's actual numbers for
   that account, run passive for a while and compare its alerts against
   his own sense of when he broke a rule.
4. **Hybrid** — only after the client has explicitly asked for the hard
   safety cutoffs to be automatic on a given account, and only on a demo
   account first. Enable it account-by-account, not all at once.
5. **Active** — revisit once hybrid has a track record on that account and
   the client wants more automated beyond the two hard cutoffs.
