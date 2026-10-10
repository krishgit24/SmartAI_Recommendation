"""Gateway orchestration for POST /retry-decision.

Order (each step is logged as a reasoning step and persisted):
  1. Duplicate / replay check  -> exact duplicate returns the stored decision
  2. Kill switch ON            -> NO_RECOMMENDATION (agent NOT called)
  3. retry_count >= max        -> DONT_RETRY + HTTP 429 (agent NOT called)
  4. Call the agent with a timeout; any error / invalid output -> NO_RECOMMENDATION
  5. Persist recommendation + agent steps, write an audit event
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError

from ..agent.interface import DecisionAgent
from ..core.config import Settings
from ..core.security import mask
from ..db.database import Database
from ..schemas import (AgentDecision, Evidence, ReasoningStep, Recommendation, RetryRecommendationRequest,
                       RetryRecommendationResponse)

log = logging.getLogger("gateway")
KILL_SWITCH_KEY = "kill_switch"
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)


class ReplayConflict(Exception):
    """Same transaction_id + retry_count with a different payload (only when policy = reject)."""


class Gateway:
    def __init__(self, settings: Settings, db: Database, agent: DecisionAgent):
        self.s = settings
        self.db = db
        self.agent = agent
        if db.get_setting(KILL_SWITCH_KEY) is None:
            db.set_setting(KILL_SWITCH_KEY, {"enabled": settings.kill_switch_default,
                                             "reason": "initial default", "actor": "system"})

    # ------------------------------------------------------------ kill switch
    def kill_switch(self) -> dict:
        st = self.db.get_setting(KILL_SWITCH_KEY)
        return {**st["value"], "updated_at": st["updated_at"]}

    def set_kill_switch(self, enabled: bool, reason: str, actor: str) -> dict:
        self.db.set_setting(KILL_SWITCH_KEY, {"enabled": enabled, "reason": reason, "actor": actor})
        self.db.add_audit("kill_switch_changed", {"enabled": enabled, "reason": reason, "actor": actor})
        log.warning("Kill switch set to %s by %s: %s", enabled, actor, reason)
        return self.kill_switch()

    # ------------------------------------------------------------ main entry
    def process(self, req: RetryRecommendationRequest) -> tuple[RetryRecommendationResponse, int]:
        started = time.perf_counter()
        correlation_id = str(uuid.uuid4())
        req_json = req.model_dump(mode="json")
        req_hash = hashlib.sha256(json.dumps(req_json, sort_keys=True).encode()).hexdigest()

        replay = self._replay_check(req, req_hash, correlation_id)
        if replay is not None:
            return replay

        steps: list[ReasoningStep] = []

        def add(action: str, observation: str, thought: str = "") -> None:
            steps.append(ReasoningStep(step=len(steps) + 1, thought=thought, action=action, observation=observation))

        http_status = 200
        decided_by = "gateway"
        agent_error: Optional[str] = None
        tool_logs: list[str] = []

        ks = self.kill_switch()
        add("check_kill_switch", f"kill switch {'ON' if ks['enabled'] else 'OFF'}",
            "Guardrail: automated decisioning must be allowed.")
        if ks["enabled"]:
            decision = AgentDecision(
                recommendation=Recommendation.NO_RECOMMENDATION, confidence_score=0.0,
                explanation=f"Automated decisioning is disabled by the kill switch (reason: {ks.get('reason')}). "
                            "The transaction is routed to Operations for manual handling.",
                human_review_required=True, rule_id="KILL_SWITCH",
                next_steps=["Manual handling by Operations (kill switch active)"],
                evidence=[Evidence(source="system", key="kill_switch", value=ks, simulated=False)],
            )
        elif req.retry_count >= self.s.max_retry_count:
            add("check_retry_budget", f"retry_count {req.retry_count} >= max {self.s.max_retry_count}",
                "Guardrail: retry budget is enforced in the backend before any agent call.")
            verb = "meets" if req.retry_count == self.s.max_retry_count else "exceeds"
            decision = AgentDecision(
                recommendation=Recommendation.DONT_RETRY, confidence_score=1.0,
                explanation=f"Max retry limit reached. The transaction has already been retried {req.retry_count} "
                            f"times, which {verb} the configured maximum (max_retry_count={self.s.max_retry_count}). "
                            "No further retries will be attempted.",
                human_review_required=True, rule_id="RETRY_BUDGET_EXHAUSTED",
                next_steps=["Route to Operations for manual resolution"],
                evidence=[Evidence(source="request", key="retry_count", value=req.retry_count, simulated=False),
                          Evidence(source="config", key="max_retry_count", value=self.s.max_retry_count,
                                   simulated=False)],
            )
            http_status = 429
        else:
            add("check_retry_budget", f"retry_count {req.retry_count} < max {self.s.max_retry_count}: OK")
            decision, agent_error = self._call_agent(req)
            decided_by = f"agent:{decision.model_used or self.agent.name}"
            for st in decision.steps:
                add(f"agent: {st.action}", st.observation, st.thought)
            tool_logs = decision.tool_logs
            if agent_error:
                add("agent_error", agent_error, "Agent failed - safe fallback applied.")

        add("final_decision", f"{decision.recommendation.value} (confidence {decision.confidence_score})")

        rec_id = str(uuid.uuid4())
        resp = RetryRecommendationResponse(
            transaction_id=req.transaction_id,
            recommendation=decision.recommendation,
            confidence_score=round(decision.confidence_score, 3),
            explanation=decision.explanation,
            optimal_timing=decision.optimal_timing,
            correction_suggestions=decision.correction_suggestions,
            recommendation_id=rec_id,
            correlation_id=correlation_id,
            decided_at=datetime.now(timezone.utc),
            human_review_required=(decision.human_review_required
                                   or decision.recommendation == Recommendation.NO_RECOMMENDATION),
            next_steps=decision.next_steps,
            evidence=decision.evidence,
            rule_id=decision.rule_id,
            decided_by=decided_by,
        )
        latency = int((time.perf_counter() - started) * 1000)
        self.db.insert_recommendation({
            "id": rec_id,
            "transaction_id": req.transaction_id,
            "retry_count": req.retry_count,
            "request_hash": req_hash,
            "correlation_id": correlation_id,
            "failure_code": req.failure_code,
            "recommendation": resp.recommendation.value,
            "confidence_score": resp.confidence_score,
            "human_review_required": int(resp.human_review_required),
            "decided_by": decided_by,
            "rule_id": resp.rule_id,
            "http_status": http_status,
            "model_used": decision.model_used,
            "request_json": json.dumps(req_json, ensure_ascii=False),
            "response_json": resp.model_dump_json(),
            "reasoning_json": json.dumps([s.model_dump() for s in steps], ensure_ascii=False),
            "tool_logs_json": json.dumps(tool_logs, ensure_ascii=False),
            "latency_ms": latency,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self.db.add_audit("recommendation_created", {
            "recommendation_id": rec_id, "recommendation": resp.recommendation.value, "rule_id": resp.rule_id,
            "confidence": resp.confidence_score, "human_review": resp.human_review_required,
            "http_status": http_status, "decided_by": decided_by, "model_used": decision.model_used,
            "agent_error": agent_error, "latency_ms": latency,
        }, req.transaction_id, correlation_id)
        log.info("txn=%s retry=%s beneficiary=%s -> %s (%s) %sms", req.transaction_id, req.retry_count,
                 mask(req.beneficiary.account_number), resp.recommendation.value, resp.rule_id, latency)
        return resp, http_status

    # ------------------------------------------------------------ helpers
    def _replay_check(self, req, req_hash: str, correlation_id: str):
        same = self.db.find_recommendation(req.transaction_id, req.retry_count, req_hash)
        if same is not None:  # exact duplicate -> idempotent replay
            resp = RetryRecommendationResponse.model_validate_json(same["response_json"])
            resp.replayed = True
            self.db.add_audit("duplicate_request_replayed", {"original_recommendation_id": same["id"]},
                              req.transaction_id, correlation_id)
            return resp, same["http_status"]
        changed = self.db.find_recommendation(req.transaction_id, req.retry_count) is not None
        max_seen = self.db.max_retry_seen(req.transaction_id)
        stale = max_seen is not None and req.retry_count < max_seen
        if changed or stale:
            event = "payload_changed" if changed else "out_of_order_retry"
            self.db.add_audit(event, {"retry_count": req.retry_count, "max_retry_seen": max_seen,
                                      "policy": self.s.duplicate_payload_policy},
                              req.transaction_id, correlation_id)
            if self.s.duplicate_payload_policy == "reject":
                raise ReplayConflict(
                    f"transaction {req.transaction_id}: "
                    + ("same retry_count already processed with a different payload" if changed
                       else f"retry_count {req.retry_count} is lower than an already processed attempt ({max_seen})"))
        return None

    def _call_agent(self, req) -> tuple[AgentDecision, Optional[str]]:
        """Calls the agent with a timeout. Never raises: failures become NO_RECOMMENDATION."""
        error: Optional[str] = None
        try:
            future = _executor.submit(self.agent.decide, req)
            raw = future.result(timeout=self.s.agent_timeout_seconds)
            decision = raw if isinstance(raw, AgentDecision) else AgentDecision.model_validate(raw)
            return decision, None
        except concurrent.futures.TimeoutError:
            error = f"agent timed out after {self.s.agent_timeout_seconds}s"
        except ValidationError as e:
            error = f"agent returned invalid output: {e.errors()[0]['msg']}"
        except Exception as e:  # noqa: BLE001 - any agent failure must fall back safely
            error = f"agent error: {type(e).__name__}: {str(e)[:200]}"
        log.error("Agent failure for txn=%s: %s", req.transaction_id, error)
        fallback = AgentDecision(
            recommendation=Recommendation.NO_RECOMMENDATION, confidence_score=0.2,
            explanation=f"Unable to produce a recommendation: the decision agent was unavailable or returned an "
                        f"invalid result ({error}). The transaction is routed to Operations.",
            human_review_required=True, rule_id="AGENT_FAILURE_FALLBACK", model_used=self.agent.name,
            next_steps=["Manual review by Operations"],
        )
        return fallback, error
