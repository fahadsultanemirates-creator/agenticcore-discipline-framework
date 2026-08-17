#!/usr/bin/env python
"""Prints a compliance stats summary from one account's (or every account's)
JSONL compliance log.

    python scripts/compliance_report.py --account account_1 --days 7
    python scripts/compliance_report.py --all --days 7   # every configured account, plus a combined total
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discipline_framework.config import PROJECT_ROOT, load_accounts, load_settings
from discipline_framework.logging_stats.stats import ComplianceReport, ComplianceStats, aggregate_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--account", help="Account id from config/accounts.yaml, e.g. account_1")
    target.add_argument("--all", action="store_true", help="Report every configured account, plus a combined total")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days (default: 7)")
    return parser.parse_args()


def _print_report(label: str, report: ComplianceReport) -> None:
    print(f"=== {label} ===")
    print(report.summary_line())
    print(f"Total checks: {report.total_checks}  Passed: {report.passed_checks}  Violations: {report.violation_count}")
    if report.violations_by_rule:
        print("Violations by rule:")
        for rule_id, count in sorted(report.violations_by_rule.items(), key=lambda kv: -kv[1]):
            print(f"  {rule_id:<32} {count}")
    if report.violations_by_severity:
        print("Violations by severity:")
        for severity, count in sorted(report.violations_by_severity.items()):
            print(f"  {severity:<10} {count}")
    print()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    log_dir = Path(settings.logging.log_dir)
    if not log_dir.is_absolute():
        log_dir = PROJECT_ROOT / log_dir
    compliance_log_dir = log_dir / settings.logging.compliance_log_dir

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    until = datetime.now(timezone.utc)

    account_ids = [args.account] if args.account else [a.id for a in load_accounts()]

    reports = []
    for account_id in account_ids:
        stats = ComplianceStats(compliance_log_dir / f"{account_id}.jsonl")
        report = stats.generate_report(since=since, until=until)
        reports.append(report)
        _print_report(account_id, report)

    if args.all and len(reports) > 1:
        _print_report("ALL ACCOUNTS (combined)", aggregate_reports(reports))


if __name__ == "__main__":
    main()
