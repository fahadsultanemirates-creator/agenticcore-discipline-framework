# AgenticCore Discipline Framework

A discipline-**enforcement** framework for a forex trader who already has a
profitable strategy but occasionally blows up an account by breaking his own
rules under emotion or impulse.

## What this is (and isn't)

- **Is:** a system that watches (and, once trusted, acts on) a trader's own
  pre-defined rules — risk per trade, stop-loss/take-profit discipline,
  cooldowns after losses, daily loss limits, session/symbol restrictions —
  and alerts or intervenes when those rules are broken.
- **Is not:** a signal generator, strategy, or "find me a good trade" system.
  It has no opinion on entries. It only checks the trader's own numbers
  against what's actually happening in the account.

## Safety posture

- **Default mode is `passive`**: the framework only observes and sends
  Telegram alerts. It never places, modifies, or closes an order.
- `active` and `hybrid` modes exist in code but are hard-gated behind two
  independent confirmations (`enforcement.allow_live_execution: true` in
  `config/settings.yaml` **and** the `DISCIPLINE_FRAMEWORK_CONFIRM_LIVE=YES`
  environment variable). Without both, the framework refuses to start in
  those modes. See [`docs/ENFORCEMENT_MODES.md`](docs/ENFORCEMENT_MODES.md).
- All numeric trading rules in `config/rules.yaml` are **placeholders**.
  They must be replaced with the client's actual numbers before this is
  used for anything but read-only monitoring in a demo/practice account.

## Project layout

```
config/
  rules.yaml          # the trader's rules — entry/exit, risk, cooldowns (PLACEHOLDERS)
  settings.yaml        # app behavior — enforcement mode, polling, logging
discipline_framework/
  config.py            # loads + validates rules.yaml / settings.yaml / .env
  rules/                # rule data models + the RuleEngine that checks them
  mt5_bridge/           # MetaTrader5 connection: real client + mock client
  enforcement/          # Passive / Active / Hybrid enforcement modes
  alerts/               # Telegram alerting
  logging_stats/        # compliance logging (JSONL) + stats reporting
  main.py               # monitoring loop entrypoint
scripts/
  run_monitor.py        # CLI entrypoint
  compliance_report.py  # prints a compliance stats summary
tests/                  # unit tests (run against the mock MT5 client)
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in MT5 + Telegram credentials
```

> `MetaTrader5` (the official Python package) only installs on Windows,
> because it wraps the MT5 terminal's native DLL. On Linux/Mac dev
> environments (including this container), install will simply skip it —
> the framework falls back to `MockMT5Client` automatically so the full
> pipeline (rules → engine → enforcement → alerts → logging) stays testable
> end-to-end without a live terminal. See `discipline_framework/mt5_bridge/`.

## Running

```bash
# Passive monitoring against the mock bridge (no MT5 terminal needed):
python scripts/run_monitor.py --mock

# Passive monitoring against a real MT5 terminal (Windows, terminal running,
# algo trading enabled, credentials in .env):
python scripts/run_monitor.py

# Compliance report:
python scripts/compliance_report.py --days 7
```

## Tests

```bash
pytest
```

Tests run entirely against the mock MT5 client and a temp log directory —
no live terminal or network access required.

## Getting the client's real rule numbers

Everything in `config/rules.yaml` is a labeled placeholder. Once we have the
client's actual numbers (max risk %, pip targets, cooldown length, session
hours, symbols, max trades/day), they drop into that one file — no code
changes needed. See the comments in that file for what each field controls
and how it's used by `discipline_framework/rules/engine.py`.
