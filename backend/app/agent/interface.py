"""The contract between the gateway (Developer A) and the AI Decision Agent (Developer B).

Developer B implements a class with this method and the gateway calls it:

    class MyAgent:
        name = "llm-agent"
        def decide(self, request: RetryRecommendationRequest) -> AgentDecision: ...

Rules for the agent implementation:
- Return an AgentDecision (see app/schemas/models.py). Anything else is rejected by the gateway.
- Raising an exception is fine: the gateway converts it to NO_RECOMMENDATION and logs it.
- The gateway has ALREADY checked the kill switch and the retry budget before calling decide().
- The agent must never execute a payment or a retry.
"""
from __future__ import annotations

from typing import Protocol

from ..schemas import AgentDecision, RetryRecommendationRequest


class DecisionAgent(Protocol):
    name: str

    def decide(self, request: RetryRecommendationRequest) -> AgentDecision:
        ...


class AgentUnavailable(Exception):
    """Raise this when the LLM provider / tools are unreachable."""
