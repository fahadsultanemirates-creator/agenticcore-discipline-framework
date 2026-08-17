#!/usr/bin/env python
"""Standalone Telegram command bot: no MT5 connection of its own. Reads and
writes each account's rules/pause state on disk — the same files an
AccountWorker (run_account.py, or run_monitor.py's in-process workers)
reloads each cycle. This is the recommended way to run the command
interface separately from any account's monitoring loop.

    python scripts/run_bot.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discipline_framework.main import build_command_only_bot


def main() -> None:
    bot = build_command_only_bot()
    try:
        bot.run_forever()
    except KeyboardInterrupt:
        bot.stop()


if __name__ == "__main__":
    main()
