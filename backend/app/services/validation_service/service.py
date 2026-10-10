
from app.services.agent_service.models import (
    AgentAction,
    AgentResponse,
    AgentTurn,
    Recommendation,
)


def validate_final_response(turn: AgentTurn) -> AgentResponse:
    if turn.action != AgentAction.FINAL:
        raise ValueError("Expected a FINAL agent action.")

    if turn.recommendation is None:
        raise ValueError("Recommendation is missing.")

    if not turn.justification or not turn.justification.strip():
        raise ValueError("Justification is missing.")

    if (
        turn.recommendation == Recommendation.RETRY_AFTER_UPDATE
        and not turn.correction_suggestions
    ):
        raise ValueError(
            "RETRY_AFTER_UPDATE requires a correction suggestion."
        )

    if (
        turn.recommendation == Recommendation.RETRY_LATER
        and not turn.optimal_timing
    ):
        raise ValueError(
            "RETRY_LATER requires a timing suggestion."
        )

    return AgentResponse(
        recommendation=turn.recommendation,
        justification=turn.justification,
        failure_category=turn.failure_category,
        correction_suggestions=turn.correction_suggestions,
        optimal_timing=turn.optimal_timing,
        confidence=turn.confidence,
    )
