"""Admin endpoints: kill switch (state-changing call needs header X-Admin-Token)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..core.security import require_admin
from ..schemas import KillSwitchRequest, KillSwitchState

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/kill-switch", response_model=KillSwitchState)
def get_kill_switch(request: Request):
    return request.app.state.gateway.kill_switch()


@router.post("/kill-switch", response_model=KillSwitchState, dependencies=[Depends(require_admin)])
def set_kill_switch(body: KillSwitchRequest, request: Request):
    """ON = stop all automated decisions; every transaction gets NO_RECOMMENDATION (manual ops)."""
    return request.app.state.gateway.set_kill_switch(body.enabled, body.reason, body.actor)
