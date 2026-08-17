"""Loads and validates config/rules.yaml + config/settings.yaml, and reads
secrets (MT5 login, Telegram token) from the environment / .env.

Kept as one module so there's exactly one place that knows about file
paths and env var names — everything else takes typed objects.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from discipline_framework.rules.models import Severity, TradingRules

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES_PATH = PROJECT_ROOT / "config" / "rules.yaml"
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"
# Sparse patch of rules changed live via Telegram commands, layered on top
# of rules.yaml at load time. Runtime state, not hand-edited — gitignored.
DEFAULT_RULES_OVERRIDES_PATH = PROJECT_ROOT / "config" / "rules_overrides.yaml"


class EnforcementSettings(BaseModel):
    mode: Literal["passive", "active", "hybrid"] = "passive"
    allow_live_execution: bool = False


class MonitoringSettings(BaseModel):
    poll_interval_seconds: int = Field(gt=0, default=30)
    history_lookback_days: int = Field(gt=0, default=2)


class MT5Settings(BaseModel):
    force_mock: bool = False


class TelegramSettings(BaseModel):
    enabled: bool = True
    min_severity: Severity = Severity.WARNING
    commands_enabled: bool = True
    # Empty = open access. See config/settings.yaml's comment on this field
    # and docs/TELEGRAM_COMMANDS.md before handing off to the client.
    authorized_user_ids: list[int] = Field(default_factory=list)


class LoggingSettings(BaseModel):
    log_dir: str = "logs"
    audit_log_file: str = "audit.log"
    compliance_log_file: str = "compliance_log.jsonl"
    level: str = "INFO"


class Settings(BaseModel):
    enforcement: EnforcementSettings
    monitoring: MonitoringSettings
    mt5: MT5Settings
    telegram: TelegramSettings
    logging: LoggingSettings


@dataclass
class MT5Credentials:
    login: int | None
    password: str | None
    server: str | None
    terminal_path: str | None


@dataclass
class TelegramCredentials:
    bot_token: str | None
    chat_id: str | None


def load_trading_rules(path: Path = DEFAULT_RULES_PATH) -> TradingRules:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return TradingRules.model_validate(raw)


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> Settings:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Settings.model_validate(raw)


def load_mt5_credentials() -> MT5Credentials:
    login = os.environ.get("MT5_LOGIN") or None
    return MT5Credentials(
        login=int(login) if login else None,
        password=os.environ.get("MT5_PASSWORD") or None,
        server=os.environ.get("MT5_SERVER") or None,
        terminal_path=os.environ.get("MT5_TERMINAL_PATH") or None,
    )


def load_telegram_credentials() -> TelegramCredentials:
    return TelegramCredentials(
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
        chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
    )
