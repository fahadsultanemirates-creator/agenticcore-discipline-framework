# Telegram command interface

Lets the trader adjust his own rules live, via chat, instead of editing a
`config/rules/<account_id>.yaml` file and restarting. One bot manages every
account (`config/accounts.yaml`) — nearly every command takes an
`account_id` as its first argument. Runs alongside the monitoring loop(s)
in its own thread/process (`discipline_framework/commands/`) — see
[`docs/MULTI_ACCOUNT.md`](MULTI_ACCOUNT.md) for the process topology.

## Commands

| Command | Effect |
|---|---|
| `/accounts` | Lists every account this bot manages, with mode and paused/active state |
| `/setrisk <account_id> <percent>` | Max risk per trade, e.g. `/setrisk account_1 1.5` |
| `/setdailyloss <account_id> <percent>` | Max daily loss threshold, e.g. `/setdailyloss account_1 5` |
| `/setcooldown <account_id> <losses> <minutes>` | Consecutive losses that trigger a cooldown, and its length, e.g. `/setcooldown account_1 2 60` |
| `/setpairs <account_id> <symbol,symbol,...>` | Symbol whitelist, e.g. `/setpairs account_1 EURUSD,GBPUSD,USDJPY` |
| `/setsession <account_id> <HH:MM-HH:MM>` or a name | Active trading hours in UTC, e.g. `/setsession account_1 07:00-16:00` or `/setsession account_1 london` (presets: `london`, `new_york`, `asian`/`tokyo`, `overlap`) |
| `/setmaxtrades <account_id> <number>` | Max new trades per day, e.g. `/setmaxtrades account_1 5` |
| `/status <account_id>` or `/status all` | Shows every currently active rule for that account (or every account), plus enforcement mode and paused/active state |
| `/pause <account_id>` or `/pause all` | Disables enforcement for that account (or every account) — no alerts, no auto-actions — without touching any rule value |
| `/resume <account_id>` or `/resume all` | Re-enables enforcement |
| `/help` | This list |

Every `/set*` command validates the new value the same way a
`config/rules/<account_id>.yaml` file is validated at startup (via the same
pydantic models) — an out-of-range or malformed value is rejected with a
clear error and nothing changes. An unknown `account_id` is rejected the
same way, with the list of known accounts in the reply. A successful change
takes effect on that account's *next* monitoring cycle; there's no restart
needed.

## How live changes relate to config/rules/\<account_id\>.yaml

Each account's `config/rules/<account_id>.yaml` stays the hand-edited,
commented baseline for that account. Telegram changes are tracked
separately, per account, as a sparse patch in
`config/rules_overrides/<account_id>.yaml` (git-ignored, created at
runtime) — only the fields actually changed via chat for that account, not
a full copy of its rules file. On load, the override patch is layered on
top of whatever's currently in that account's baseline. Practically:

- A dev can still edit an account's rules file for fields the trader hasn't
  touched via Telegram, and that edit takes effect normally.
- A field the trader *has* set via Telegram for a given account keeps his
  value until he changes it again via Telegram for that account (or someone
  deletes that account's override file).
- `discipline_framework/rules/store.py`'s `RulesStore` is the only thing
  that reads/writes an override file — see that file for the merge logic —
  and each account gets its own `RulesStore` instance.

Either way — an account's YAML or a Telegram command naming it — the same
`RulesStore` is what that account's `RuleEngine` reads from, so enforcement
behaves identically regardless of where a rule's current value came from.

If the bot and an account's monitoring loop run in different processes (the
recommended production topology, see docs/MULTI_ACCOUNT.md), the change
still reaches the right account: `RulesStore.reload_if_stale()` re-reads
that account's files from disk once per monitoring cycle, so a command
issued to the bot process shows up in the worker process on its next poll
— typically within one `poll_interval_seconds`.

## Access control

`config/settings.yaml`'s `telegram.authorized_user_ids` is a **single,
global** whitelist of Telegram numeric user IDs — it applies to every
account, not per-account. See docs/MULTI_ACCOUNT.md for why: this bot
manages every account for one trader, so a single whitelist matches the
actual access model. **It ships empty**, which means open access — anyone
who messages the bot can change any account's live trading rules. That's
intentional for the development/testing phase; the app logs a loud warning
on every startup while the list is empty, so it's never silently forgotten.

An unauthorized user's command gets an explicit "🚫 Not authorized" reply
(never a silent no-op), and the attempt is logged to the audit log with
their Telegram user ID.

**Before handing this off to the client:** set
`telegram.authorized_user_ids` to just his ID, e.g. `[123456789]`. To find
it: have him message the bot once and check `logs/audit.log` for the
`user_id` in the "Command from user_id=..." line, or point him at
`@userinfobot` on Telegram.

## Pausing vs. changing enforcement mode

`/pause <account_id>` and `/resume <account_id>` don't touch that account's
`enforcement.mode` in `config/accounts.yaml` (passive/hybrid/active) or any
rule value — they just toggle whether that account's enforcer acts on this
cycle's results. Rule checks keep running and keep being logged to that
account's compliance log while paused, so compliance stats stay continuous;
only the alerting/auto-action step is skipped. This is meant for short
deliberate breaks on one account (e.g. "I know I'm about to take a
discretionary trade on account_1 outside the rules, don't alert me for the
next 10 minutes") — remember to `/resume` afterward, since there's no
auto-expiry. Use `/pause all` for a deployment-wide emergency stop across
every account at once.
