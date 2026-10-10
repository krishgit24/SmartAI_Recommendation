from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


def utc_now():
    return datetime.now(timezone.utc)


# ==========================================
# ENUMS
# ==========================================

class RecommendationType(str, Enum):
    RETRY_NOW = "RETRY_NOW"
    RETRY_LATER = "RETRY_LATER"
    DONT_RETRY = "DONT_RETRY"
    RETRY_AFTER_UPDATE = "RETRY_AFTER_UPDATE"
    NO_RECOMMENDATION = "NO_RECOMMENDATION"


class TransactionStatus(str, Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    MANUAL_REVIEW = "manual_review"


class FinalOutcome(str, Enum):
    RECOVERED = "recovered"
    FAILED = "failed"
    UNRESOLVED = "unresolved"


# ==========================================
# 1. TRANSACTIONS
# Collection: transactions
# ==========================================

class TransactionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    failure_code: str
    failure_category: str

    retry_count: int = Field(default=0, ge=0)

    processing_status: TransactionStatus = (
        TransactionStatus.RECEIVED
    )

    final_outcome: FinalOutcome | None = None

    createdAt: datetime = Field(default_factory=utc_now)


# ==========================================
# 2. RECOMMENDATIONS
# Collection: recommendations
# ==========================================

class RecommendationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str

    recommendation: RecommendationType
    confidence_score: float = Field(ge=0, le=1)
    explanation: str

    optimal_timing: datetime | None = None

    correction_suggestions: dict[str, Any] | None = None

    decision_source: str
    http_status: int = Field(ge=100, le=599)

    createdAt: datetime = Field(default_factory=utc_now)


# ==========================================
# 3. AGENT AUDIT LOGS
# Collection: agent_audit_logs
# ==========================================

class AgentAuditLogSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    execution_id: str

    # Ordered actions, tool calls and observations
    steps: list[dict[str, Any]] = Field(default_factory=list)

    validation_status: str
    agent_attempts: int = Field(default=0, ge=0, le=3)
    reasoning_cycles: int = Field(default=0, ge=0, le=5)

    final_recommendation: RecommendationType | None = None

    error_message: str | None = None
    total_duration_ms: int = Field(default=0, ge=0)

    createdAt: datetime = Field(default_factory=utc_now)


# ==========================================
# 4. SYSTEM CONFIGS
# Collection: system_configs
# ==========================================

class SystemConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_key: str = "retry_engine"

    kill_switch_enabled: bool = False

    max_retry_count: int = Field(default=3, ge=0)
    max_agent_attempts: int = Field(default=3, ge=0, le=3)
    max_agent_loops: int = Field(default=5, ge=0, le=5)

    updated_by: str | None = None
    updatedAt: datetime = Field(default_factory=utc_now)
