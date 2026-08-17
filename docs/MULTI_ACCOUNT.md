# Multi-account architecture

The client splits funds across several MT5 accounts rather than trading one
big account. This document covers how the framework was restructured to
support that, and the reasoning behind the choices that aren't obvious from
reading the code alone.

## What's per-account vs. global, and why

| Setting | Scope | Where |
|---|---|---|
| Trading rules (risk %, cooldown, session, symbols, ...) | **Per account** | `config/rules/<account_id>.yaml` |
| Enforcement mode (passive/hybrid/active) | **Per account** | `config/accounts.yaml` |
| `allow_live_execution` | **Per account** | `config/accounts.yaml` |
| MT5 login/password/server | **Per account** | `.env`, named per account in `config/accounts.yaml` |
| `DISCIPLINE_FRAMEWORK_CONFIRM_LIVE` | **Global** (one deployment-wide switch) | environment variable |
| Telegram `authorized_user_ids` whitelist | **Global** | `config/settings.yaml` |
| Poll interval, history lookback | **Global** | `config/settings.yaml` |
| Telegram bot token, alert severity threshold | **Global** | `config/settings.yaml` / `.env` |

The rule of thumb: **anything that expresses risk tolerance or trading
behavior is per-account**, because that's the entire point of this
change — the client wants accounts that can genuinely differ from each
other. **Anything that's about the deployment or the operator/trader
relationship stays global**, because there's one bot, one Telegram
conversation, and (for this client) one person managing every account.

Two calls worth flagging explicitly, since the task asked us to:

- **`DISCIPLINE_FRAMEWORK_CONFIRM_LIVE` is global, not per-account.**
  `allow_live_execution` in `config/accounts.yaml` already lets each
  account opt in/out of live execution independently. Layering a *second*,
  deployment-wide environment variable on top means turning on live trading
  for a new or additional account is a one-line YAML change (reviewable in
  a diff), but it still can't take effect unless someone has separately and
  deliberately set that environment variable on that specific
  machine/session. If this were per-account instead, it would just be a
  second YAML flag next to the first, with no real independent safety
  value — the point of an env-var gate is that it's *not* checked into the
  repo, so it has to stay a single, once-per-deployment decision to keep
  that property.

- **`authorized_user_ids` is global, not per-account.** This framework is
  built for one trader running several accounts of his own — there's no
  scenario yet where different people should be allowed to command
  different accounts. A single whitelist is simpler and matches the actual
  threat model (a stranger finding the bot and tinkering with *any*
  account's live rules). If this is ever extended to a team managing
  different accounts, the natural extension is an optional per-account
  `authorized_user_ids` override list in `config/accounts.yaml` that
  falls back to the global list — `CommandHandlers._resolve()` in
  `discipline_framework/commands/handlers.py` is the one place that would
  need to grow an authorization check to support it.

## Why each account needs its own process (eventually)

The official `MetaTrader5` Python package wraps a single MT5 terminal
installation's native DLL and only supports **one active terminal
connection per OS process** — calling `mt5.initialize()` again just
reconnects that same process to a different account rather than adding a
second simultaneous connection. Two accounts genuinely running
*simultaneously* against the real bridge therefore need two separate
terminal installations *and* two separate Python processes.

This shaped the architecture in two ways:

1. **`AccountRuntime` and `AccountWorker`** (`discipline_framework/accounts.py`)
   bundle everything one account needs — bridge, `RulesStore`,
   `PausableEnforcer`, `RuleEngine`, `ComplianceLogger` — with nothing
   shared with any other account's runtime. An `AccountWorker` doesn't know
   or care whether it's running as a thread alongside others or as the only
   thing in its process.
2. **Cross-process coordination happens through the filesystem, not shared
   memory.** `RulesStore.reload_if_stale()` and
   `PausableEnforcer.sync_from_disk()` re-read that account's rules and
   pause-state files (by checking mtimes) once per monitoring cycle. This
   is what lets a Telegram command — issued to a bot process that may not
   even be the same process as the account's worker — reach that worker on
   its next poll, with no message queue, socket, or shared object required.
   It also means the *exact same code* is correct whether everything runs
   in one process or several: reload/sync are cheap `stat()` calls that
   simply find nothing changed when the writer is in the same process
   sharing the same objects.

## Two supported topologies

**Single process, threaded (`scripts/run_monitor.py`)** — every enabled
account's `AccountWorker` plus the Telegram bot run as threads in one
Python process. This is what the mock bridge is built for (`--mock`), and
it's fine for the real bridge too *as long as at most one account in that
process uses it* — the moment a second real account joins, its
`mt5.initialize()` call would silently steal the connection from the first.
Good for local development, demos, and testing the pipeline end-to-end.

**One process per account (recommended for real multi-account trading)** —
`scripts/run_account.py <account_id>` runs a single account standalone
(its own MT5 terminal connection, if not `--mock`), and
`scripts/run_bot.py` runs only the Telegram interface with no MT5
connection of its own. Run one `run_account.py` per real account plus one
`run_bot.py`, and they coordinate purely through the on-disk state
described above. This is the only topology that's actually correct for
more than one account on the real MT5 bridge at once.

Both topologies build from the exact same `AccountRuntime`/`AccountWorker`
code in `discipline_framework/accounts.py` — nothing about the rule engine,
enforcement, or logging differs between them.

## Per-account state on disk

```
config/
  accounts.yaml                    # the account list (committed)
  rules/<account_id>.yaml          # each account's rule baseline (committed)
  rules_overrides/<account_id>.yaml  # live Telegram changes, sparse patch (gitignored)
state/
  <account_id>.json                 # {"paused": bool} — /pause and /resume (gitignored)
logs/
  audit.log                         # shared, human-readable, lines tagged "[account_id] ..."
  compliance/<account_id>.jsonl     # one compliance log per account, records also carry account_id
```

Renaming an account's `id` in `config/accounts.yaml` changes which override
file, state file, and compliance log it maps to — do that before real data
accumulates under the old id, not after (there's no automatic migration).

## Reporting: per-account and combined

`scripts/compliance_report.py --account <id>` reports one account.
`--all` reports every configured account individually, then a combined
total via `discipline_framework/logging_stats/stats.aggregate_reports()`,
which sums counts and merges violation breakdowns across
already-generated per-account `ComplianceReport`s. Compliance logs are
never physically merged — aggregation happens at report-generation time
from the separate per-account files, so each account's raw log stays a
clean, independent audit trail.
