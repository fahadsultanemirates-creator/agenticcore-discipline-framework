#!/usr/bin/env python
"""Standalone single-account monitoring process — the recommended way to
run more than one account against the real MT5 bridge simultaneously (the
MetaTrader5 SDK only supports one terminal connection per process). Run one
of these per account, plus run_bot.py for the shared Telegram interface.

    python scripts/run_account.py account_1 --mock   # mock bridge, no terminal needed
    python scripts/run_account.py account_1          # real MT5 bridge (Windows + terminal)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discipline_framework.main import build_single_account_worker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("account_id", help="Account id from config/accounts.yaml, e.g. account_1")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use the in-memory mock MT5 bridge instead of a real terminal connection.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    worker = build_single_account_worker(args.account_id, use_mock=args.mock)
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    main()
