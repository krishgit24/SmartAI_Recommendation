"""Gateway settings, read from environment variables (.env supported).

No secrets are hard-coded. Copy .env.example to .env and edit it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _list(name: str, default: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.getenv(name, default).split(",") if x.strip())


@dataclass
class Settings:
    app_name: str = "Smart Recommendation API (Prototype)"
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "smart_recommendation.db"))

    # guardrails enforced by the gateway BEFORE the agent is called
    max_retry_count: int = field(default_factory=lambda: _int("MAX_RETRY_COUNT", 3))
    kill_switch_default: bool = field(default_factory=lambda: _bool("KILL_SWITCH_DEFAULT", False))
    admin_token: str = field(default_factory=lambda: os.getenv("ADMIN_TOKEN", "change-me-local-only"))

    # agent call
    agent_mode: str = field(default_factory=lambda: os.getenv("AGENT_MODE", "stub"))  # stub | real
    agent_timeout_seconds: float = field(default_factory=lambda: _float("AGENT_TIMEOUT_SECONDS", 30.0))

    # same transaction_id + retry_count with a DIFFERENT payload: reprocess (audit it) or reject (HTTP 409)
    duplicate_payload_policy: str = field(default_factory=lambda: os.getenv("DUPLICATE_PAYLOAD_POLICY", "reprocess"))

    cors_origins: tuple[str, ...] = field(default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:4200"))

    def validate(self) -> None:
        if self.max_retry_count < 1:
            raise ValueError("MAX_RETRY_COUNT must be >= 1")
        if self.agent_mode not in {"stub", "real"}:
            raise ValueError("AGENT_MODE must be 'stub' or 'real'")
        if self.duplicate_payload_policy not in {"reprocess", "reject"}:
            raise ValueError("DUPLICATE_PAYLOAD_POLICY must be 'reprocess' or 'reject'")


def get_settings() -> Settings:
    s = Settings()
    s.validate()
    return s
