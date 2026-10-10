"""Pydantic models.

Request/response field names follow the official contract
(contracts/smart_recommendation_api.yaml). Extra response fields are additive
and optional, so a client that only knows the official contract keeps working.

`AgentDecision` is the AGREED HAND-OFF between the gateway (Developer A) and the
AI Decision Agent (Developer B).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import PaymentRail, Recommendation


# ------------------------------------------------------------------ request
class PartyDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=200)
    account_number: str = Field(min_length=4, max_length=64)
    bic_code: str = Field(min_length=8, max_length=11)

    @field_validator("bic_code")
    @classmethod
    def bic_format(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.isalnum():
            raise ValueError("bic_code must be alphanumeric")
        return v

    @field_validator("account_number")
    @classmethod
    def account_chars(cls, v: str) -> str:
        # spaces/hyphens are allowed on purpose: a spaced IBAN is a real failure case (scenario E3C)
        if not all(c.isalnum() or c in " -" for c in v):
            raise ValueError("account_number may contain only letters, digits, spaces and hyphens")
        return v


class RetryRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")  # unknown fields are dropped, never passed on

    transaction_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    amount: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    payment_rail: PaymentRail
    failure_code: str = Field(min_length=1, max_length=64)
    failure_reason: str = Field(min_length=1, max_length=2000)
    ordering_customer: PartyDetails
    beneficiary: PartyDetails
    timestamp: datetime
    retry_count: int = Field(default=0, ge=0, le=1000)

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, v: str) -> str:
        if not v.isalpha():
            raise ValueError("currency must be a 3-letter ISO code")
        return v.upper()

    @field_validator("failure_code")
    @classmethod
    def norm_code(cls, v: str) -> str:
        return v.strip().upper()


# ------------------------------------------------------------------ reasoning / evidence
class ReasoningStep(BaseModel):
    step: int
    thought: str = ""
    action: str
    observation: str


class Evidence(BaseModel):
    source: str
    key: str
    value: Any = None
    simulated: bool = True


# ------------------------------------------------------------------ gateway <-> agent contract
class AgentDecision(BaseModel):
    """What the agent (Developer B) must return to the gateway.

    The gateway validates it with Pydantic. If the agent raises, times out or
    returns something invalid, the gateway returns NO_RECOMMENDATION.
    """

    model_config = ConfigDict(extra="forbid")

    recommendation: Recommendation
    confidence_score: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=1)
    optimal_timing: Optional[datetime] = None
    correction_suggestions: Optional[list[str]] = None
    human_review_required: bool = False
    next_steps: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    steps: list[ReasoningStep] = Field(default_factory=list)  # Thought -> Action -> Observation
    tool_logs: list[str] = Field(default_factory=list)
    rule_id: Optional[str] = None
    model_used: Optional[str] = None  # e.g. "stub", "gpt-4o-mini"

    @model_validator(mode="after")
    def field_rules(self) -> "AgentDecision":
        if self.recommendation == Recommendation.RETRY_LATER and self.optimal_timing is None:
            raise ValueError("optimal_timing is required for RETRY_LATER")
        if self.recommendation == Recommendation.RETRY_AFTER_UPDATE and not self.correction_suggestions:
            raise ValueError("correction_suggestions are required for RETRY_AFTER_UPDATE")
        return self


# ------------------------------------------------------------------ response
class RetryRecommendationResponse(BaseModel):
    # official contract fields
    transaction_id: str
    recommendation: Recommendation
    confidence_score: float = Field(ge=0, le=1)
    explanation: str
    optimal_timing: Optional[datetime] = None
    correction_suggestions: Optional[list[str]] = None

    # additive prototype fields
    recommendation_id: Optional[str] = None
    correlation_id: Optional[str] = None
    decided_at: Optional[datetime] = None
    human_review_required: bool = False
    next_steps: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    rule_id: Optional[str] = None
    decided_by: Optional[str] = None  # "gateway" or "agent:<model>"
    replayed: bool = False
    simulated: bool = True
    disclaimer: str = ("Prototype recommendation based on SIMULATED bank data. "
                       "No payment or retry is executed by this system.")

    @model_validator(mode="after")
    def field_rules(self) -> "RetryRecommendationResponse":
        # contract: timing only for RETRY_LATER, suggestions only for RETRY_AFTER_UPDATE
        if self.recommendation == Recommendation.RETRY_LATER:
            if self.optimal_timing is None:
                raise ValueError("optimal_timing is required for RETRY_LATER")
        else:
            self.optimal_timing = None
        if self.recommendation == Recommendation.RETRY_AFTER_UPDATE:
            if not self.correction_suggestions:
                raise ValueError("correction_suggestions are required for RETRY_AFTER_UPDATE")
        else:
            self.correction_suggestions = None
        return self


# ------------------------------------------------------------------ observability / admin
class TransactionAuditRecord(BaseModel):
    transaction_id: str
    timestamp: datetime
    recommendation: str
    status: str
    confidence_score: Optional[float] = None
    failure_code: Optional[str] = None
    human_review_required: Optional[bool] = None
    retry_count: Optional[int] = None


class AgentReasoning(BaseModel):
    transaction_id: str
    recommendation_id: Optional[str] = None
    decided_by: Optional[str] = None
    thought_process: list[ReasoningStep]
    tool_logs: list[str]


class KillSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    reason: str = Field(min_length=3, max_length=300)
    actor: str = Field(default="ops-user", min_length=1, max_length=64)


class KillSwitchState(BaseModel):
    enabled: bool
    reason: Optional[str] = None
    actor: Optional[str] = None
    updated_at: Optional[str] = None
