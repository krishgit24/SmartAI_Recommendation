"""STUB agent - lets the gateway be built and demoed before the real AI agent is ready.

It makes NO bank calls and uses NO LLM. It maps the failure code to a fixed
answer so every recommendation type can be exercised end to end. Every answer is
clearly labelled as coming from the stub. Replace with the real agent by setting
AGENT_MODE=real once Developer B's agent is merged.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..schemas import AgentDecision, ReasoningStep, Recommendation, RetryRecommendationRequest

STUB_NOTE = "[STUB AGENT - no bank lookup or AI used]"


class StubAgent:
    name = "stub"

    def decide(self, request: RetryRecommendationRequest) -> AgentDecision:
        code = request.failure_code
        step = ReasoningStep(step=1, thought="Stub: map failure code to a fixed recommendation.",
                             action="stub_lookup", observation=f"failure_code={code}")

        if code in {"NETWORK_TIMEOUT", "PROCESSING_ERROR"}:
            rec, conf, text, kw = Recommendation.RETRY_NOW, 0.9, "Transient technical failure.", {}
        elif code == "GATEWAY_TIMEOUT":
            rec, conf, text = Recommendation.RETRY_LATER, 0.85, "Beneficiary bank assumed unavailable."
            kw = {"optimal_timing": datetime.now(timezone.utc) + timedelta(hours=1)}
        elif code in {"INVALID_ACCOUNT", "NAME_MISMATCH", "INSUFFICIENT_FUNDS"}:
            rec, conf, text = Recommendation.RETRY_AFTER_UPDATE, 0.8, "Payment data needs an authorised correction."
            kw = {"correction_suggestions": ["Verify the beneficiary details with the ordering customer."],
                  "human_review_required": True}
        elif code in {"ACCOUNT_CLOSED", "SANCTIONS_HIT"}:
            rec, conf, text, kw = Recommendation.DONT_RETRY, 0.95, "Terminal failure.", {"human_review_required": True}
        else:
            rec, conf, text = Recommendation.NO_RECOMMENDATION, 0.3, "Unknown failure code."
            kw = {"human_review_required": True}

        return AgentDecision(
            recommendation=rec, confidence_score=conf, explanation=f"{STUB_NOTE} {text}",
            steps=[step], tool_logs=[], rule_id=f"STUB_{rec.value}", model_used="stub", **kw,
        )
