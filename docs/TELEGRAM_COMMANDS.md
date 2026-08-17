# Telegram command interface

Lets the trader adjust his own rules live, via chat, instead of editing
`config/rules.yaml` and restarting. Runs alongside the monitoring loop in
its own background thread (`discipline_framework/commands/`).

## Commands

| Command | Effect |
|---|---|
| `/setrisk <percent>` | Max risk per trade, e.g. `/setrisk 1.5` |
| `/setdailyloss <percent>` | Max daily loss threshold, e.g. `/setdailyloss 5` |
| `/setcooldown <losses> <minutes>` | Consecutive losses that trigger a cooldown, and its length, e.g. `/setcooldown 2 60` |
| `/setpairs <symbol,symbol,...>` | Symbol whitelist, e.g. `/setpairs EURUSD,GBPUSD,USDJPY` |
| `/setsession <HH:MM-HH:MM>` or a name | Active trading hours in UTC, e.g. `/setsession 07:00-16:00` or `/setsession london` (presets: `london`, `new_york`, `asian`/`tokyo`, `overlap`) |
| `/setmaxtrades <number>` | Max new trades per day, e.g. `/setmaxtrades 5` |
| `/status` | Shows every currently active rule, plus enforcement mode and paused/active state |
| `/pause` | Disables enforcement (no alerts, no auto-actions) without touching any rule value |
| `/resume` | Re-enables enforcement |
| `/help` | This list |

Every `/set*` command validates the new value the same way `config/rules.yaml`
is validated at startup (via the same pydantic models) — an out-of-range or
malformed value is rejected with a clear error and nothing changes. A
successful change takes effect on the *next* monitoring cycle; there's no
restart needed.

## How live changes relate to config/rules.yaml

`config/rules.yaml` stays the hand-edited, commented baseline. Telegram
changes are tracked separately as a sparse patch in
`config/rules_overrides.yaml` (git-ignored, created at runtime) — only the
fields actually changed via chat, not a full copy of the rules file. On
startup, the override patch is layered on top of whatever's currently in
`rules.yaml`. Practically:

- A dev can still edit `rules.yaml` for fields the trader hasn't touched via
  Telegram, and that edit takes effect normally.
- A field the trader *has* set via Telegram keeps his value until he changes
  it again via Telegram (or someone deletes `config/rules_overrides.yaml`).
- `discipline_framework/rules/store.py`'s `RulesStore` is the only thing
  that reads/writes `rules_overrides.yaml` — see that file for the merge
  logic.

Either way — YAML or Telegram — the same `RulesStore` is what `RuleEngine`
reads from, so enforcement behaves identically regardless of where a rule's
current value came from.

## Access control

`config/settings.yaml`'s `telegram.authorized_user_ids` is a whitelist of
Telegram numeric user IDs. **It ships empty**, which means open access —
anyone who messages the bot can change live trading rules. That's
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

`/pause` and `/resume` don't touch `enforcement.mode` in
`config/settings.yaml` (passive/hybrid/active) or any rule value — they
just toggle whether the enforcer acts on this cycle's results. Rule checks
keep running and keep being logged to the compliance log while paused, so
compliance stats stay continuous; only the alerting/auto-action step is
skipped. This is meant for short deliberate breaks (e.g. "I know I'm about
to take a discretionary trade outside the rules, don't alert me for the
next 10 minutes") — remember to `/resume` afterward, since there's no
auto-expiry.
