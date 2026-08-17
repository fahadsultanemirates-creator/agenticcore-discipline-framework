"""Compliance stats derived from the JSONL compliance log — the numbers
behind things like "rules followed 87% of trades this week" or "3
discipline saves this month."
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HARD_SAFETY_RULE_IDS = {"max_daily_loss", "max_daily_loss_open_positions", "consecutive_loss_cooldown"}


@dataclass
class ComplianceReport:
    period_start: datetime
    period_end: datetime
    total_checks: int
    passed_checks: int
    violation_count: int
    compliance_rate: float  # 0-100, 100 if there were no checks in the period
    violations_by_rule: dict[str, int]
    violations_by_severity: dict[str, int]
    discipline_saves: int

    def summary_line(self) -> str:
        return (
            f"Rules followed on {self.compliance_rate:.0f}% of checks "
            f"({self.period_start:%Y-%m-%d} to {self.period_end:%Y-%m-%d}), "
            f"{self.violation_count} violation(s) flagged, "
            f"{self.discipline_saves} discipline save(s)."
        )


class ComplianceStats:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path

    def generate_report(self, since: datetime, until: datetime | None = None) -> ComplianceReport:
        until = until or datetime.now(timezone.utc)
        records = [r for r in self._read_records() if since <= _parse_ts(r["timestamp"]) <= until]

        total = len(records)
        passed = sum(1 for r in records if r["passed"])
        violations = total - passed

        by_rule = Counter(r["rule_id"] for r in records if not r["passed"])
        by_severity = Counter(r["severity"] for r in records if not r["passed"])
        compliance_rate = (passed / total * 100) if total else 100.0

        return ComplianceReport(
            period_start=since,
            period_end=until,
            total_checks=total,
            passed_checks=passed,
            violation_count=violations,
            compliance_rate=compliance_rate,
            violations_by_rule=dict(by_rule),
            violations_by_severity=dict(by_severity),
            discipline_saves=self._count_discipline_saves(records),
        )

    def _read_records(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        records = []
        with self.log_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    @staticmethod
    def _count_discipline_saves(records: list[dict]) -> int:
        """Heuristic pending real usage data: counts distinct *incidents* of
        a hard-safety rule firing (max daily loss / cooldown violation),
        collapsing consecutive same-rule-same-ticket failures from repeated
        polling cycles into a single incident, so a 30-second poll interval
        doesn't inflate one breach into dozens of "saves."

        In passive mode this reads as "times the framework caught something
        and told him" — the leading indicator the client actually asked
        for. Once active/hybrid mode is enabled for real, this becomes
        literal: one incident corresponds to one auto-blocked action.
        """
        incidents = 0
        last_key = None
        for record in sorted(records, key=lambda r: r["timestamp"]):
            if record["passed"] or record["rule_id"] not in HARD_SAFETY_RULE_IDS:
                continue
            key = (record["rule_id"], record.get("context", {}).get("ticket"))
            if key != last_key:
                incidents += 1
            last_key = key
        return incidents


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
