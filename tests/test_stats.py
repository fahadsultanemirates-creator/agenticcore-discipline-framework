from __future__ import annotations

from datetime import datetime, timedelta, timezone

from discipline_framework.logging_stats.logger import ComplianceLogger
from discipline_framework.logging_stats.stats import ComplianceStats
from discipline_framework.rules.models import CheckResult, Severity
from tests.test_rule_engine import make_snapshot

BASE = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def result(rule_id, passed, severity=Severity.WARNING, **context):
    return CheckResult(rule_id=rule_id, passed=passed, severity=severity, message="x", context=context)


def test_compliance_rate_and_violation_breakdown(tmp_path):
    log_path = tmp_path / "compliance_log.jsonl"
    logger = ComplianceLogger(log_path)

    logger.log_cycle(
        make_snapshot(as_of=BASE),
        [result("stop_loss_required", True), result("allowed_symbol", True)],
        mode="passive",
    )
    logger.log_cycle(
        make_snapshot(as_of=BASE + timedelta(minutes=1)),
        [result("stop_loss_required", False, severity=Severity.CRITICAL), result("allowed_symbol", True)],
        mode="passive",
    )

    stats = ComplianceStats(log_path)
    report = stats.generate_report(since=BASE - timedelta(hours=1), until=BASE + timedelta(hours=1))

    assert report.total_checks == 4
    assert report.passed_checks == 3
    assert report.violation_count == 1
    assert report.compliance_rate == 75.0
    assert report.violations_by_rule == {"stop_loss_required": 1}
    assert report.violations_by_severity == {"critical": 1}


def test_discipline_saves_collapses_repeated_polling_of_same_incident(tmp_path):
    log_path = tmp_path / "compliance_log.jsonl"
    logger = ComplianceLogger(log_path)

    # Same cooldown violation on the same ticket, polled 3 times in a row —
    # should collapse to a single "save," not three.
    for i in range(3):
        logger.log_cycle(
            make_snapshot(as_of=BASE + timedelta(seconds=30 * i)),
            [result("consecutive_loss_cooldown", False, severity=Severity.CRITICAL, ticket=42)],
            mode="passive",
        )
    # A distinct incident on a different ticket afterwards.
    logger.log_cycle(
        make_snapshot(as_of=BASE + timedelta(minutes=10)),
        [result("consecutive_loss_cooldown", False, severity=Severity.CRITICAL, ticket=99)],
        mode="passive",
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
