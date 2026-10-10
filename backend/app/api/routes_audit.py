"""Observability endpoints: reasoning view, audit trail, live transaction ticker."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request

from ..schemas import AgentReasoning, ReasoningStep, RetryRecommendationResponse, TransactionAuditRecord

router = APIRouter(tags=["Observability"])


@router.get("/transactions/{transaction_id}/recommendation", response_model=RetryRecommendationResponse)
def latest_recommendation(transaction_id: str, request: Request):
    row = request.app.state.db.latest_recommendation(transaction_id)
    if row is None:
        raise HTTPException(404, "no recommendation for this transaction")
    return RetryRecommendationResponse.model_validate_json(row["response_json"])


@router.get("/transactions/{transaction_id}/reasoning", response_model=AgentReasoning)
def reasoning(transaction_id: str, request: Request):
    """Official contract: Thought -> Action -> Observation steps + tool logs."""
    row = request.app.state.db.latest_recommendation(transaction_id)
    if row is None:
        raise HTTPException(404, "no recommendation for this transaction")
    return AgentReasoning(
        transaction_id=transaction_id, recommendation_id=row["id"], decided_by=row["decided_by"],
        thought_process=[ReasoningStep(**x) for x in json.loads(row["reasoning_json"])],
        tool_logs=json.loads(row["tool_logs_json"]),
    )


@router.get("/dashboard/transactions", response_model=list[TransactionAuditRecord])
def transactions(request: Request, limit: int = Query(50, ge=1, le=500)):
    """Official contract: live ticker of recent decisions."""
    out = []
    for r in request.app.state.db.recent(limit):
        out.append(TransactionAuditRecord(
            transaction_id=r["transaction_id"], timestamp=r["created_at"], recommendation=r["recommendation"],
            status="HUMAN_REVIEW" if r["human_review_required"] else "AUTO_RECOMMENDED",
            confidence_score=r["confidence_score"], failure_code=r["failure_code"],
            human_review_required=bool(r["human_review_required"]), retry_count=r["retry_count"]))
    return out


@router.get("/audit/{transaction_id}")
def audit(transaction_id: str, request: Request):
    events = request.app.state.db.audit_for(transaction_id)
    if not events:
        raise HTTPException(404, "no audit events for this transaction")
    return {"transaction_id": transaction_id, "events": events}
