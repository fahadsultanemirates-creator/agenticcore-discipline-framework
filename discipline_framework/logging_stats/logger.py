"""Two separate logs, kept deliberately distinct:

- The audit log (stdlib `logging`, human-readable) — connections, errors,
  mode changes, enforcement actions. For a person auditing what the system
  did.
- The compliance log (JSONL, one record per rule check per cycle) — for
  stats.py to compute compliance rate / violations / discipline-save counts
  from. Every rule check gets a record, passed or not, so the denominator
  for "% of checks followed" is always the full picture, not just failures.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

from discipline_framework.mt5_bridge.models import AccountSnapshot
from discipline_framework.rules.models import CheckResult


def setup_logging(log_dir: Path, audit_log_file: str, level: str = "INFO") -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("discipline_framework")
    root.setLevel(level)
    root.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / audit_log_file, maxBytes=5_000_000, backupCount=5
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


class ComplianceLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log_cycle(self, snapshot: AccountSnapshot, results: list[CheckResult], mode: str) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            for result in results:
                record = {
                    "timestamp": snapshot.as_of.isoformat(),
                    "mode": mode,
                    "rule_id": result.rule_id,
                    "passed": result.passed,
                    "severity": result.severity.value,
                    "message": result.message,
                    "context": result.context,
                }
                f.write(json.dumps(record) + "\n")
