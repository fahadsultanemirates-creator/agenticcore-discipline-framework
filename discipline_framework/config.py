"""Loads and validates config/settings.yaml (global) and config/accounts.yaml
(one entry per MT5 account), and reads secrets (MT5 logins, Telegram token)
from the environment / .env.

Split of "global" vs "per-account" settings, and why:

- monitoring (poll interval, history lookback), mt5.force_mock, telegram
  (bot token/whitelist/alert threshold), and logging are GLOBAL — one
  Telegram bot serves every account, and there's no reason two accounts on
  the same deployment would want different polling cadence or a different
  set of people allowed to command the bot.
- enforcement mode, allow_live_execution, the trading rules themselves, and
  MT5 credentials are PER-ACCOUNT (config/accounts.yaml + config/rules/) —
  the whole point of this change is that accounts can run different risk
  settings and different enforcement postures independently.

Kept as one module so there's exactly one place that knows about file paths
and env var names — everything else takes typed objects.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from discipline_framework.rules.models import Severity, TradingRules

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"
DEFAULT_ACCOUNTS_PATH = PROJECT_ROOT / "config" / "accounts.yaml"
# Per-account hand-edited, commented rule baselines live here as
# <account_id>.yaml (config/accounts.yaml's rules_file usually points here).
DEFAULT_RULES_DIR = PROJECT_ROOT / "config" / "rules"
# Per-account sparse patches of rules changed live via Telegram, one file
# per account: <account_id>.yaml. Runtime state, not hand-edited — gitignored.
DEFAULT_RULES_OVERRIDES_DIR = PROJECT_ROOT / "config" / "rules_overrides"
# Per-account pause/resume state, so /pause survives a restart and is
# visible to a monitoring process running separately from the command bot.
DEFAULT_CONTROL_STATE_DIR = PROJECT_ROOT / "state"


class MonitoringSettings(BaseModel):
    poll_interval_seconds: int = Field(gt=0, default=30)
    history_lookback_days: int = Field(gt=0, default=2)


class MT5Settings(BaseModel):
    force_mock: bool = False


class TelegramSettings(BaseModel):
    enabled: bool = True
    min_severity: Severity = Severity.WARNING
    commands_enabled: bool = True
    # Empty = open access, applies to ALL accounts. See config/settings.yaml's
    # comment on this field and docs/TELEGRAM_COMMANDS.md before handing off.
    authorized_user_ids: list[int] = Field(default_factory=list)


class LoggingSettings(BaseModel):
    log_dir: str = "logs"
    audit_log_file: str = "audit.log"
    # Per-account compliance logs live at <log_dir>/<compliance_log_dir>/<account_id>.jsonl
    compliance_log_dir: str = "compliance"
    level: str = "INFO"


class Settings(BaseModel):
    monitoring: MonitoringSettings
    mt5: MT5Settings
    telegram: TelegramSettings
    logging: LoggingSettings


class AccountMT5Config(BaseModel):
    """Names of the environment variables holding this account's MT5
    credentials — not the credentials themselves, which stay in .env. Each
    account uses distinct env var names so one .env file can hold every
    account's secrets side by side, e.g. MT5_ACCOUNT_1_LOGIN,
    MT5_ACCOUNT_2_LOGIN."""

    login_env: str
    password_env: str
    server_env: str
    terminal_path_env: str | None = None


class AccountEnforcementConfig(BaseModel):
    mode: Literal["passive", "active", "hybrid"] = "passive"
    allow_live_execution: bool = False


class AccountConfig(BaseModel):
    id: str
    display_name: str = ""
    enabled: bool = True
    # Path to this account's rule baseline, relative to the project root,
    # e.g. "config/rules/account_1.yaml". Each account can point at its own
    # file, or share one if two accounts should genuinely run identical
    # rules — nothing requires them to differ.
    rules_file: str
    mt5: AccountMT5Config
    enforcement: AccountEnforcementConfig = Field(default_factory=AccountEnforcementConfig)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not value or not all(c.isalnum() or c in "_-" for c in value):
            raise ValueError(f"account id {value!r} must be non-empty and alphanumeric (with _ or -)")
        return value

    @property
    def label(self) -> str:
        return self.display_name or self.id


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


def load_trading_rules(path: Path) -> TradingRules:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return TradingRules.model_validate(raw)


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> Settings:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Settings.model_validate(raw)


def load_accounts(path: Path = DEFAULT_ACCOUNTS_PATH) -> list[AccountConfig]:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    accounts = [AccountConfig.model_validate(entry) for entry in raw.get("accounts", [])]

    ids = [a.id for a in accounts]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Duplicate account id(s) in {path}: {duplicates}")
    if not accounts:
        raise ValueError(f"No accounts defined in {path}")
    return accounts


def rules_path_for(account: AccountConfig) -> Path:
    path = Path(account.rules_file)
    return path if path.is_absolute() else PROJECT_ROOT / path


def rules_overrides_path_for(account: AccountConfig) -> Path:
    return DEFAULT_RULES_OVERRIDES_DIR / f"{account.id}.yaml"


def control_state_path_for(account: AccountConfig) -> Path:
    return DEFAULT_CONTROL_STATE_DIR / f"{account.id}.json"


def load_mt5_credentials(account: AccountConfig) -> MT5Credentials:
    login = os.environ.get(account.mt5.login_env) or None
    return MT5Credentials(
        login=int(login) if login else None,
        password=os.environ.get(account.mt5.password_env) or None,
        server=os.environ.get(account.mt5.server_env) or None,
        terminal_path=os.environ.get(account.mt5.terminal_path_env or "") or None,
    )


def load_telegram_credentials() -> TelegramCredentials:
    return TelegramCredentials(
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
        chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
    )
