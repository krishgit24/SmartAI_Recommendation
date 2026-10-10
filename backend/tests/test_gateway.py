"""Gateway tests - run against the stub agent and fake agents (no bank, no LLM, no network)."""
import time

from app.schemas import AgentDecision, Recommendation
from conftest import ADMIN, base_request


class SpyAgent:
    """Counts calls so we can prove the agent is NOT called when a guardrail fires."""
    name = "spy"

    def __init__(self, result=None, error=None, sleep=0):
        self.calls, self.result, self.error, self.sleep = 0, result, error, sleep

    def decide(self, request):
        self.calls += 1
        if self.sleep:
            time.sleep(self.sleep)
        if self.error:
            raise self.error
        return self.result or AgentDecision(recommendation=Recommendation.RETRY_NOW, confidence_score=0.9,
                                            explanation="spy says retry", model_used="spy")


# ------------------------------------------------------------------ basics
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["agent"] == "stub"


def test_swagger(client):
    assert client.get("/docs").status_code == 200


def test_stub_covers_all_recommendation_types(client):
    expected = {"NETWORK_TIMEOUT": "RETRY_NOW", "GATEWAY_TIMEOUT": "RETRY_LATER",
                "INVALID_ACCOUNT": "RETRY_AFTER_UPDATE", "ACCOUNT_CLOSED": "DONT_RETRY",
                "SOMETHING_ELSE": "NO_RECOMMENDATION"}
    for i, (code, rec) in enumerate(expected.items()):
        body = client.post("/retry-decision", json=base_request(transaction_id=f"T{i}", failure_code=code)).json()
        assert body["recommendation"] == rec
        assert (body["optimal_timing"] is not None) == (rec == "RETRY_LATER")
        assert (body["correction_suggestions"] is not None) == (rec == "RETRY_AFTER_UPDATE")


# ------------------------------------------------------------------ validation -> 400
def test_invalid_payloads_return_400(client):
    bad = [
        {k: v for k, v in base_request().items() if k != "beneficiary"},
        base_request(amount=-5),
        base_request(payment_rail="CARRIER_PIGEON"),
        base_request(currency="US"),
        base_request(beneficiary={"account_number": "DE89<script>"}),
        base_request(transaction_id="TXN 1; DROP TABLE"),
        base_request(retry_count=-1),
    ]
    for body in bad:
        r = client.post("/retry-decision", json=body)
        assert r.status_code == 400, body
        assert r.json()["error"] == "invalid_request"


# ------------------------------------------------------------------ guardrails
def test_retry_budget_429_and_agent_not_called(make_client):
    spy = SpyAgent()
    c = make_client(agent=spy)
    for rc in (3, 5, 10):
        r = c.post("/retry-decision", json=base_request(transaction_id=f"T{rc}", retry_count=rc))
        body = r.json()
        assert r.status_code == 429
        assert body["recommendation"] == "DONT_RETRY" and body["confidence_score"] == 1.0
        assert "Max retry limit reached" in body["explanation"]
    assert spy.calls == 0


def test_below_limit_calls_agent(make_client):
    spy = SpyAgent()
    c = make_client(agent=spy)
    assert c.post("/retry-decision", json=base_request(retry_count=2)).status_code == 200
    assert spy.calls == 1


def test_custom_retry_limit(make_client):
    c = make_client(max_retry_count=5)
    assert c.post("/retry-decision", json=base_request(retry_count=4)).status_code == 200
    assert c.post("/retry-decision", json=base_request(transaction_id="T2", retry_count=5)).status_code == 429


def test_kill_switch_requires_token(client):
    assert client.post("/admin/kill-switch", json={"enabled": True, "reason": "test"}).status_code == 401
    assert client.post("/admin/kill-switch", json={"enabled": True, "reason": "test"},
                       headers={"X-Admin-Token": "wrong"}).status_code == 401


def test_kill_switch_blocks_agent_and_wins_over_budget(make_client):
    spy = SpyAgent()
    c = make_client(agent=spy)
    r = c.post("/admin/kill-switch", json={"enabled": True, "reason": "incident drill"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert c.get("/admin/kill-switch").json()["enabled"] is True
    body = c.post("/retry-decision", json=base_request()).json()
    assert body["recommendation"] == "NO_RECOMMENDATION" and body["rule_id"] == "KILL_SWITCH"
    assert body["human_review_required"] is True
    r = c.post("/retry-decision", json=base_request(transaction_id="T9", retry_count=9))
    assert r.json()["recommendation"] == "NO_RECOMMENDATION"
    assert spy.calls == 0
    c.post("/admin/kill-switch", json={"enabled": False, "reason": "drill over"}, headers=ADMIN)
    assert c.post("/retry-decision", json=base_request(transaction_id="T3")).json()["recommendation"] == "RETRY_NOW"
    assert spy.calls == 1


def test_kill_switch_survives_restart(make_client):
    make_client().post("/admin/kill-switch", json={"enabled": True, "reason": "persist me"}, headers=ADMIN)
    assert make_client().get("/admin/kill-switch").json()["enabled"] is True


# ------------------------------------------------------------------ agent failures -> safe fallback
def test_agent_exception_gives_no_recommendation(make_client):
    c = make_client(agent=SpyAgent(error=RuntimeError("LLM provider down")))
    body = c.post("/retry-decision", json=base_request()).json()
    assert body["recommendation"] == "NO_RECOMMENDATION"
    assert body["rule_id"] == "AGENT_FAILURE_FALLBACK"
    assert "LLM provider down" in body["explanation"]


def test_agent_invalid_output_gives_no_recommendation(make_client):
    class BadAgent:
        name = "bad"

        def decide(self, request):
            return {"recommendation": "MAYBE", "confidence_score": 7}

    body = make_client(agent=BadAgent()).post("/retry-decision", json=base_request()).json()
    assert body["recommendation"] == "NO_RECOMMENDATION" and "invalid output" in body["explanation"]


def test_agent_retry_later_without_timing_is_rejected(make_client):
    class Sloppy:
        name = "sloppy"

        def decide(self, request):
            return {"recommendation": "RETRY_LATER", "confidence_score": 0.8, "explanation": "later"}

    body = make_client(agent=Sloppy()).post("/retry-decision", json=base_request()).json()
    assert body["recommendation"] == "NO_RECOMMENDATION"


def test_agent_timeout(make_client):
    c = make_client(agent=SpyAgent(sleep=1.0), agent_timeout_seconds=0.2)
    body = c.post("/retry-decision", json=base_request()).json()
    assert body["recommendation"] == "NO_RECOMMENDATION" and "timed out" in body["explanation"]


# ------------------------------------------------------------------ duplicates / replay
def test_exact_duplicate_returns_stored_decision(make_client):
    spy = SpyAgent()
    c = make_client(agent=spy)
    first = c.post("/retry-decision", json=base_request()).json()
    second = c.post("/retry-decision", json=base_request()).json()
    assert second["replayed"] is True and second["recommendation_id"] == first["recommendation_id"]
    assert spy.calls == 1
    assert len(c.get("/dashboard/transactions").json()) == 1


def test_changed_payload_reprocessed_and_audited(client):
    client.post("/retry-decision", json=base_request())
    r = client.post("/retry-decision", json=base_request(failure_code="ACCOUNT_CLOSED"))
    assert r.status_code == 200 and r.json()["recommendation"] == "DONT_RETRY"
    events = [e["event_type"] for e in client.get("/audit/TXN-TEST-1").json()["events"]]
    assert "payload_changed" in events


def test_strict_mode_rejects_changed_payload_and_out_of_order(make_client):
    c = make_client(duplicate_payload_policy="reject")
    c.post("/retry-decision", json=base_request(retry_count=2))
    assert c.post("/retry-decision", json=base_request(retry_count=2, amount=9)).status_code == 409
    assert c.post("/retry-decision", json=base_request(retry_count=1)).status_code == 409


# ------------------------------------------------------------------ persistence & observability
def test_reasoning_and_audit_persisted(client):
    client.post("/retry-decision", json=base_request())
    reasoning = client.get("/transactions/TXN-TEST-1/reasoning").json()
    actions = [s["action"] for s in reasoning["thought_process"]]
    assert actions[0] == "check_kill_switch" and actions[1] == "check_retry_budget"
    assert any(a.startswith("agent:") for a in actions) and actions[-1] == "final_decision"
    assert reasoning["decided_by"] == "agent:stub"
    events = client.get("/audit/TXN-TEST-1").json()["events"]
    assert events[-1]["event_type"] == "recommendation_created"
    assert client.get("/transactions/TXN-TEST-1/recommendation").json()["recommendation"] == "RETRY_NOW"


def test_persistence_survives_restart(make_client):
    make_client().post("/retry-decision", json=base_request())
    assert make_client().get("/transactions/TXN-TEST-1/recommendation").status_code == 200


def test_dashboard_transactions(client):
    client.post("/retry-decision", json=base_request(transaction_id="A"))
    client.post("/retry-decision", json=base_request(transaction_id="B", retry_count=3))
    rows = client.get("/dashboard/transactions").json()
    assert {r["transaction_id"] for r in rows} == {"A", "B"}
    assert {r["status"] for r in rows} == {"AUTO_RECOMMENDED", "HUMAN_REVIEW"}


def test_404s(client):
    assert client.get("/transactions/NOPE/reasoning").status_code == 404
    assert client.get("/audit/NOPE").status_code == 404
