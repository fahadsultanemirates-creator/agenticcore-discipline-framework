from __future__ import annotations

from datetime import datetime, timedelta, timezone

from discipline_framework.logging_stats.logger import ComplianceLogger
from discipline_framework.logging_stats.stats import ComplianceStats, aggregate_reports
from discipline_framework.rules.models import CheckResult, Severity
from tests.test_rule_engine import make_snapshot

BASE = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def result(rule_id, passed, severity=Severity.WARNING, **context):
    return CheckResult(rule_id=rule_id, passed=passed, severity=severity, message="x", context=context)


def test_compliance_rate_and_violation_breakdown(tmp_path):
    log_path = tmp_path / "account_1.jsonl"
    logger = ComplianceLogger(log_path)

    logger.log_cycle(
        make_snapshot(as_of=BASE),
        [result("stop_loss_required", True), result("allowed_symbol", True)],
        mode="passive",
        account_id="account_1",
    )
    logger.log_cycle(
        make_snapshot(as_of=BASE + timedelta(minutes=1)),
        [result("stop_loss_required", False, severity=Severity.CRITICAL), result("allowed_symbol", True)],
        mode="passive",
        account_id="account_1",
    )

    stats = ComplianceStats(log_path)
    report = stats.generate_report(since=BASE - timedelta(hours=1), until=BASE + timedelta(hours=1))

    assert report.total_checks == 4
    assert report.passed_checks == 3
    assert report.violation_count == 1
    assert report.compliance_rate == 75.0
    assert report.violations_by_rule == {"stop_loss_required": 1}
    assert report.violations_by_severity == {"critical": 1}


def test_log_records_carry_account_id(tmp_path):
    log_path = tmp_path / "account_2.jsonl"
    logger = ComplianceLogger(log_path)
    logger.log_cycle(make_snapshot(as_of=BASE), [result("allowed_symbol", True)], mode="passive", account_id="account_2")

    import json

    with log_path.open() as f:
        record = json.loads(f.readline())
    assert record["account_id"] == "account_2"


def test_discipline_saves_collapses_repeated_polling_of_same_incident(tmp_path):
    log_path = tmp_path / "account_1.jsonl"
    logger = ComplianceLogger(log_path)

    # Same cooldown violation on the same ticket, polled 3 times in a row —
    # should collapse to a single "save," not three.
    for i in range(3):
        logger.log_cycle(
            make_snapshot(as_of=BASE + timedelta(seconds=30 * i)),
            [result("consecutive_loss_cooldown", False, severity=Severity.CRITICAL, ticket=42)],
            mode="passive",
            account_id="account_1",
        )
    # A distinct incident on a different ticket afterwards.
    logger.log_cycle(
        make_snapshot(as_of=BASE + timedelta(minutes=10)),
        [result("consecutive_loss_cooldown", False, severity=Severity.CRITICAL, ticket=99)],
        mode="passive",
        account_id="account_1",
    )

    stats = ComplianceStats(log_path)
    report = stats.generate_report(since=BASE - timedelta(hours=1), until=BASE + timedelta(hours=1))
    assert report.discipline_saves == 2


def test_empty_log_reports_full_compliance(tmp_path):
    stats = ComplianceStats(tmp_path / "does_not_exist.jsonl")
    report = stats.generate_report(since=BASE - timedelta(hours=1))
    assert report.total_checks == 0
    assert report.compliance_rate == 100.0
    assert report.discipline_saves == 0


def test_aggregate_reports_combines_multiple_accounts(tmp_path):
    log_1 = tmp_path / "account_1.jsonl"
    log_2 = tmp_path / "account_2.jsonl"
    logger_1 = ComplianceLogger(log_1)
    logger_2 = ComplianceLogger(log_2)

    logger_1.log_cycle(
        make_snapshot(as_of=BASE),
        [result("stop_loss_required", True), result("allowed_symbol", False, severity=Severity.WARNING)],
        mode="passive",
        account_id="account_1",
    )
    logger_2.log_cycle(
        make_snapshot(as_of=BASE),
        [result("max_daily_loss", False, severity=Severity.CRITICAL)],
        mode="passive",
        account_id="account_2",
    )

    since, until = BASE - timedelta(hours=1), BASE + timedelta(hours=1)
    report_1 = ComplianceStats(log_1).generate_report(since=since, until=until)
    report_2 = ComplianceStats(log_2).generate_report(since=since, until=until)

    combined = aggregate_reports([report_1, report_2])
    assert combined.total_checks == 3
    assert combined.passed_checks == 1
    assert combined.violation_count == 2
    assert combined.violations_by_rule == {"allowed_symbol": 1, "max_daily_loss": 1}
    assert combined.violations_by_severity == {"warning": 1, "critical": 1}


def test_aggregate_reports_requires_at_least_one():
    import pytest

    with pytest.raises(ValueError):
        aggregate_reports([])
