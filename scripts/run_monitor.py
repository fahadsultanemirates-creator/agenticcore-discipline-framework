#!/usr/bin/env python
"""All-in-one entrypoint: every enabled account (config/accounts.yaml) plus
the Telegram command bot, in a single process.

    python scripts/run_monitor.py --mock   # mock MT5 bridge, no terminal needed
    python scripts/run_monitor.py          # real MT5 bridge (Windows + terminal)

Good for local dev/testing and for small deployments on the mock bridge.
For a real multi-account deployment with more than one account on the real
MT5 bridge, use one process per account instead — see run_account.py,
run_bot.py, and docs/MULTI_ACCOUNT.md for why (the MetaTrader5 SDK only
supports one terminal connection per process).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discipline_framework.main import build_supervisor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use the in-memory mock MT5 bridge for every account instead of a real terminal connection.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_supervisor(use_mock=args.mock).run_forever()


if __name__ == "__main__":
    main()
