#!/usr/bin/env python
"""Prints a compliance stats summary from the JSONL compliance log.

    python scripts/compliance_report.py --days 7
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discipline_framework.config import PROJECT_ROOT, load_settings
from discipline_framework.logging_stats.stats import ComplianceStats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days (default: 7)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    log_dir = Path(settings.logging.log_dir)
    if not log_dir.is_absolute():
        log_dir = PROJECT_ROOT / log_dir
    log_path = log_dir / settings.logging.compliance_log_file

    stats = ComplianceStats(log_path)
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    report = stats.generate_report(since=since)

    print(report.summary_line())
    print(f"\nTotal checks: {report.total_checks}  Passed: {report.passed_checks}  Violations: {report.violation_count}")
    if report.violations_by_rule:
        print("\nViolations by rule:")
        for rule_id, count in sorted(report.violations_by_rule.items(), key=lambda kv: -kv[1]):
            print(f"  {rule_id:<32} {count}")
    if report.violations_by_severity:
        print("\nViolations by severity:")
        for severity, count in sorted(report.violations_by_severity.items()):
            print(f"  {severity:<10} {count}")


if __name__ == "__main__":
    main()
