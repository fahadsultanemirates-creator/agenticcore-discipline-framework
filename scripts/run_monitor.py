#!/usr/bin/env python
"""CLI entrypoint for the monitoring loop.

    python scripts/run_monitor.py --mock   # mock MT5 bridge, no terminal needed
    python scripts/run_monitor.py          # real MT5 bridge (Windows + terminal)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discipline_framework.main import build_monitoring_loop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use the in-memory mock MT5 bridge instead of a real terminal connection.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    loop = build_monitoring_loop(use_mock=args.mock)
    loop.run_forever()


if __name__ == "__main__":
    main()
