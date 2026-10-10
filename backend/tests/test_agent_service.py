
import pytest

from app.services.agent_service.models import (
    AgentAction,
    AgentTurn,
    Recommendation,
    FailureCategory,
)
from app.services.agent_service.service import AgentService
from tests.fake_bank_client import FakeBankClient


class FakeLLM:
    def __init__(self):
        self.calls = 0

    async def get_next_turn(
        self,
        request,
        observations,
        available_tools,
    ):
        self.calls += 1

        if self.calls == 1:
            return AgentTurn(
                action=AgentAction.CALL_TOOL,
                rationale="Account information is needed.",
                tool_name="get_account",
                tool_arguments={"account_number": "TEST-123"},
            )

        assert len(observations) == 1
        assert observations[0]["result"]["ok"] is True

        return AgentTurn(
            action=AgentAction.FINAL,
            rationale="The test fixture reports an active account.",
            recommendation=Recommendation.RETRY_NOW,
            failure_category=FailureCategory.TECHNICAL,
            justification=(
                "Test-only recommendation using the supplied fixture."
            ),
            confidence=0.9,
        )


class EndlessToolLLM:
    def __init__(self):
        self.calls = 0

    async def get_next_turn(
        self,
        request,
        observations,
        available_tools,
    ):
        self.calls += 1

        return AgentTurn(
            action=AgentAction.CALL_TOOL,
            rationale="Requesting another test lookup.",
            tool_name="get_account",
            tool_arguments={"account_number": "TEST-123"},
        )


@pytest.mark.asyncio
async def test_agent_calls_tool_and_returns_valid_response():
    llm = FakeLLM()
    agent = AgentService(FakeBankClient(), llm_service=llm)

    result = await agent.run({
        "transaction_id": "TEST-TXN-001",
        "failure_code": "TIMEOUT",
        "account_number": "TEST-123",
    })

    assert result.response.recommendation == Recommendation.RETRY_NOW
    assert len(result.steps) == 2
    assert result.steps[0].action == "get_account"
    assert result.steps[1].action == "FINAL"
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_agent_stops_after_five_cycles():
    llm = EndlessToolLLM()
    agent = AgentService(FakeBankClient(), llm_service=llm)

    result = await agent.run({
        "transaction_id": "TEST-TXN-002",
        "failure_code": "UNKNOWN",
    })

    assert llm.calls == 5
    assert result.response.recommendation == (
        Recommendation.NO_RECOMMENDATION
    )
