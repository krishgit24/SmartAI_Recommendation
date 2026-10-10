
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Recommendation(str, Enum):
    RETRY_NOW = "RETRY_NOW"
    RETRY_LATER = "RETRY_LATER"
    RETRY_AFTER_UPDATE = "RETRY_AFTER_UPDATE"
    DONT_RETRY = "DONT_RETRY"
    NO_RECOMMENDATION = "NO_RECOMMENDATION"


class FailureCategory(str, Enum):
    TECHNICAL = "TECHNICAL"
    DATA_MISMATCH = "DATA_MISMATCH"
    COMPLIANCE = "COMPLIANCE"
    ACCOUNT_ERROR = "ACCOUNT_ERROR"
    UNKNOWN = "UNKNOWN"


class AgentAction(str, Enum):
    CALL_TOOL = "CALL_TOOL"
    FINAL = "FINAL"


class AgentTurn(BaseModel):
    """One structured LLM response in the agent loop."""

    model_config = ConfigDict(extra="forbid")

    action: AgentAction
    rationale: str = Field(
        min_length=1,
        description="Concise decision summary, not private chain-of-thought",
    )

    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)

    recommendation: Recommendation | None = None
    failure_category: FailureCategory = FailureCategory.UNKNOWN
    justification: str | None = None

    correction_suggestions: list[str] = Field(default_factory=list)
    optimal_timing: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.action == AgentAction.CALL_TOOL:
            if not self.tool_name:
                raise ValueError("CALL_TOOL requires tool_name")

            if self.recommendation is not None:
                raise ValueError(
                    "CALL_TOOL must not include a final recommendation"
                )

        if self.action == AgentAction.FINAL:
            if self.tool_name is not None:
                raise ValueError("FINAL must not include tool_name")

            if self.recommendation is None:
                raise ValueError("FINAL requires a recommendation")

            if not self.justification or not self.justification.strip():
                raise ValueError("FINAL requires a justification")

        return self


class AgentResponse(BaseModel):
    recommendation: Recommendation
    justification: str
    failure_category: FailureCategory

    correction_suggestions: list[str] = Field(default_factory=list)
    optimal_timing: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class AgentStep(BaseModel):
    """A concise, auditable record of an agent action."""

    step: int
    rationale: str
    action: str
    observation: str


class AgentResult(BaseModel):
    response: AgentResponse
    steps: list[AgentStep] = Field(default_factory=list)
    failure_category: FailureCategory = FailureCategory.UNKNOWN
