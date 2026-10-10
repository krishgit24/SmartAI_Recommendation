
import json
from typing import Any

from pydantic import BaseModel

from app.services.agent_service.models import (
    AgentAction,
    AgentResponse,
    AgentResult,
    AgentStep,
    AgentTurn,
    FailureCategory,
    Recommendation,
)
from app.services.llm_service import LLMService
from app.services.tool_registry import ToolRegistry
from app.services.validation_service import validate_final_response


MAX_AGENT_CYCLES = 5


def to_dict(request: Any) -> dict[str, Any]:
    if isinstance(request, BaseModel):
        return request.model_dump(mode="json")

    if isinstance(request, dict):
        return request

    raise ValueError("Request must be a Pydantic model or dictionary.")


def safe_fallback(
    steps: list[AgentStep],
    reason: str,
) -> AgentResult:
    response = AgentResponse(
        recommendation=Recommendation.NO_RECOMMENDATION,
        justification=(
            "A validated recommendation could not be produced. "
            "Manual operations review is required."
        ),
        failure_category=FailureCategory.UNKNOWN,
        correction_suggestions=[],
        optimal_timing=None,
        confidence=0.0,
    )

    steps.append(
        AgentStep(
            step=len(steps) + 1,
            rationale="Safe fallback selected.",
            action="FALLBACK",
            observation=reason,
        )
    )

    return AgentResult(
        response=response,
        steps=steps,
        failure_category=FailureCategory.UNKNOWN,
    )


class AgentService:
    def __init__(
        self,
        bank_client: Any,
        llm_service: Any = None,
    ):
        self.tools = ToolRegistry(bank_client)
        self.llm = (
            llm_service
            if llm_service is not None
            else LLMService()
        )

    async def run(self, request: Any) -> AgentResult:
        steps: list[AgentStep] = []
        observations: list[dict[str, Any]] = []

        try:
            transaction = to_dict(request)

            for cycle in range(1, MAX_AGENT_CYCLES + 1):
                turn: AgentTurn = await self.llm.get_next_turn(
                    request=transaction,
                    observations=observations,
                    available_tools=self.tools.descriptions(),
                )

                if turn.action == AgentAction.CALL_TOOL:
                    result = await self.tools.execute(
                        turn.tool_name or "",
                        turn.tool_arguments,
                    )

                    observations.append(
                        {
                            "tool": turn.tool_name,
                            "result": result,
                        }
                    )

                    steps.append(
                        AgentStep(
                            step=cycle,
                            rationale=turn.rationale,
                            action=turn.tool_name or "INVALID_TOOL",
                            observation=json.dumps(
                                result,
                                default=str,
                            ),
                        )
                    )

                    continue

                if turn.action == AgentAction.FINAL:
                    response = validate_final_response(turn)

                    steps.append(
                        AgentStep(
                            step=cycle,
                            rationale=turn.rationale,
                            action="FINAL",
                            observation="Final output passed validation.",
                        )
                    )

                    return AgentResult(
                        response=response,
                        steps=steps,
                        failure_category=response.failure_category,
                    )

            return safe_fallback(
                steps,
                "Maximum of five agent cycles reached.",
            )

        except Exception as exc:
            # Record a safe error category, not a stack trace or secret.
            return safe_fallback(
                steps,
                f"Agent execution failed: {type(exc).__name__}",
            )
