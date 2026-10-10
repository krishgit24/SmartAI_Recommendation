"""FastAPI entry point - Smart Recommendation gateway (prototype).

Run (from backend/):  uvicorn app.main:app --reload --port 8000
Swagger UI:           http://127.0.0.1:8000/docs
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agent.interface import DecisionAgent
from .agent.stub_agent import StubAgent
from .api import routes_admin, routes_audit, routes_decision
from .core.config import Settings, get_settings
from .core.logging_config import setup_logging
from .db.database import Database
from .services.gateway import Gateway


def build_agent(settings: Settings) -> DecisionAgent:
    if settings.agent_mode == "real":
        # Developer B: expose your agent as app/agent/real_agent.py -> class RealAgent
        from .agent.real_agent import RealAgent  # noqa: WPS433 (imported only when enabled)
        return RealAgent()
    return StubAgent()


def create_app(settings: Optional[Settings] = None, agent: Optional[DecisionAgent] = None) -> FastAPI:
    s = settings or get_settings()
    s.validate()
    setup_logging(s.log_level)
    db = Database(s.database_path)

    app = FastAPI(
        title=s.app_name,
        version="0.1.0",
        description="Gateway for failed / non-STP payment recommendations. Bank data is SIMULATED. "
                    "No payment or retry is ever executed by this system.",
    )
    app.state.settings = s
    app.state.db = db
    app.state.gateway = Gateway(s, db, agent or build_agent(s))

    app.add_middleware(CORSMiddleware, allow_origins=list(s.cors_origins), allow_methods=["*"],
                       allow_headers=["*"])

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        # Contract says 400 (FastAPI's default would be 422)
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=400, content={"error": "invalid_request", "details": errors})

    @app.get("/health", tags=["System"])
    def health():
        return {"status": "ok", "agent": app.state.gateway.agent.name,
                "kill_switch_enabled": app.state.gateway.kill_switch()["enabled"]}

    app.include_router(routes_decision.router)
    app.include_router(routes_audit.router)
    app.include_router(routes_admin.router)
    # routes_analytics.py (dashboard metrics) is owned by another team member
    return app


app = create_app()  # used by: uvicorn app.main:app
