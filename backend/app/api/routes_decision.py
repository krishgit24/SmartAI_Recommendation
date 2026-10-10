"""Decision endpoint (official contract): POST /retry-decision."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ..schemas import RetryRecommendationRequest, RetryRecommendationResponse
from ..services.gateway import ReplayConflict

router = APIRouter(tags=["Decision Engine"])


@router.post("/retry-decision", response_model=RetryRecommendationResponse,
             responses={400: {"description": "Invalid input payload"},
                        409: {"description": "Only when DUPLICATE_PAYLOAD_POLICY=reject"},
                        429: {"description": "Max retry limit reached (body = DONT_RETRY)"}})
def retry_decision(req: RetryRecommendationRequest, request: Request):
    try:
        resp, status = request.app.state.gateway.process(req)
    except ReplayConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    return JSONResponse(status_code=status, content=json.loads(resp.model_dump_json()))
