# AgenticCore Discipline Framework

A discipline-**enforcement** framework for a forex trader who already has a
profitable strategy but occasionally blows up an account by breaking his own
rules under emotion or impulse. Manages multiple MT5 accounts at once —
the client splits funds across several accounts rather than trading one big
one.

## What this is (and isn't)

- **Is:** a system that watches (and, once trusted, acts on) a trader's own
  pre-defined rules — risk per trade, stop-loss/take-profit discipline,
  cooldowns after losses, daily loss limits, session/symbol restrictions —
  and alerts or intervenes when those rules are broken, independently for
  each of his accounts.
- **Is not:** a signal generator, strategy, or "find me a good trade" system.
  It has no opinion on entries. It only checks the trader's own numbers
  against what's actually happening in each account.

## Safety posture

- **Default mode is `passive`**: the framework only observes and sends
  Telegram alerts. It never places, modifies, or closes an order.
- `active` and `hybrid` modes exist in code but are hard-gated, per
  account, behind two independent confirmations (that account's
  `enforcement.allow_live_execution: true` in `config/accounts.yaml`
  **and** the deployment-wide `DISCIPLINE_FRAMEWORK_CONFIRM_LIVE=YES`
  environment variable). Without both, the framework refuses to start that
  account in those modes — other accounts are unaffected. See
  [`docs/ENFORCEMENT_MODES.md`](docs/ENFORCEMENT_MODES.md).
- All numeric trading rules in `config/rules/*.yaml` are **placeholders**.
  They must be replaced with the client's actual numbers, per account,
  before this is used for anything but read-only monitoring in a
  demo/practice account.
- The Telegram command interface (below) ships with an **open** access
  whitelist for development. Lock it to the client's Telegram user ID
  before real money is on the line — see
  [`docs/TELEGRAM_COMMANDS.md`](docs/TELEGRAM_COMMANDS.md).

## Multiple accounts

Each account gets its own MT5 connection, its own rule file (they can run
different risk settings from each other), and its own enforcement mode —
see [`docs/MULTI_ACCOUNT.md`](docs/MULTI_ACCOUNT.md) for the full design,
including why running more than one account against the real MT5 bridge
needs one process per account (`scripts/run_account.py`), and what stays
global (one Telegram bot, one access whitelist) vs. what's per-account.

## Adjusting rules live via Telegram

Rules can also be changed via chat instead of editing a
`config/rules/<account_id>.yaml` file — `/setrisk account_1 1.5`,
`/setcooldown account_1 2 60`, `/status account_1` or `/status all`,
`/pause account_1` or `/pause all`, etc. One bot manages every account.
Live changes go through the same `RulesStore` that each account's rules
file feeds, so enforcement behaves identically regardless of where a rule's
value came from. Full command list and access-control setup:
[`docs/TELEGRAM_COMMANDS.md`](docs/TELEGRAM_COMMANDS.md).

## Project layout

```
config/
  accounts.yaml               # the list of MT5 accounts this deployment manages
  rules/<account_id>.yaml     # each account's rules — entry/exit, risk, cooldowns (PLACEHOLDERS)
  rules_overrides/<id>.yaml   # live changes made via Telegram, per account (runtime-generated, git-ignored)
  settings.yaml                # global app behavior — polling, logging, Telegram access
state/<account_id>.json       # per-account /pause state (runtime-generated, git-ignored)
discipline_framework/
  config.py              # loads + validates settings.yaml / accounts.yaml / rules files / .env
  accounts.py             # AccountRuntime + AccountWorker — one self-contained unit per account
  rules/                   # rule models, the RuleEngine, and RulesStore (live-mutable rules)
  mt5_bridge/              # MetaTrader5 connection: real client + mock client
  enforcement/             # Passive / Active / Hybrid enforcement modes + pause/resume wrapper
  alerts/                  # Telegram alerting
  commands/                 # Telegram /command interface (per-account rule changes, pause/resume)
  logging_stats/            # per-account compliance logging (JSONL) + stats + cross-account aggregation
  main.py                   # multi-account supervisor entrypoint
scripts/
  run_monitor.py         # all accounts + bot in one process (dev/mock/small deployments)
  run_account.py         # one account, standalone process (recommended for real multi-account trading)
  run_bot.py              # Telegram command interface only, no MT5 connection
  compliance_report.py   # per-account or combined compliance stats summary
tests/                   # unit tests (run against the mock MT5 client, no network)
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in per-account MT5 credentials + Telegram credentials
```

> `MetaTrader5` (the official Python package) only installs on Windows,
> because it wraps the MT5 terminal's native DLL, and only supports one
> terminal connection per process — see docs/MULTI_ACCOUNT.md for what that
> means for running several accounts at once. On Linux/Mac dev environments
> (including this container), install will simply skip it — the framework
> falls back to `MockMT5Client` automatically so the full pipeline (rules →
> engine → enforcement → alerts → logging) stays testable end-to-end
> without a live terminal. See `discipline_framework/mt5_bridge/`.

## Running

```bash
# Every account + the bot, one process, mock bridge (no MT5 terminal needed):
python scripts/run_monitor.py --mock

# Every account + the bot, one process, real MT5 (fine for a single real
# account; see docs/MULTI_ACCOUNT.md before pointing more than one at the
# real bridge from the same process):
python scripts/run_monitor.py

# Recommended for real multi-account trading: one process per account,
# plus one for the bot.
python scripts/run_account.py account_1
python scripts/run_account.py account_2
python scripts/run_bot.py

# Compliance report:
python scripts/compliance_report.py --account account_1 --days 7
python scripts/compliance_report.py --all --days 7   # every account + a combined total
```

## Tests

```bash
pytest
```

Tests run entirely against the mock MT5 client and temp directories — no
live terminal or network access required.

## Getting the client's real rule numbers

Everything in `config/rules/account_1.yaml` and `config/rules/account_2.yaml`
is a labeled placeholder (`account_1`/`account_2` are placeholder ids —
rename them to the client's real account names once we have them, along
with `config/accounts.yaml`). Once we have the client's actual numbers per
account (max risk %, pip targets, cooldown length, session hours, symbols,
max trades/day), they drop into that account's rules file — no code changes
needed. See the comments in `config/rules/account_1.yaml` for what each
field controls and how it's used by `discipline_framework/rules/engine.py`.
They can also be set directly by the client via Telegram commands once he
has bot access — see
[`docs/TELEGRAM_COMMANDS.md`](docs/TELEGRAM_COMMANDS.md).
