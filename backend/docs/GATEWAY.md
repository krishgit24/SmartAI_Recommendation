# Gateway & Database (Developer A)

## Run (Windows PowerShell, from `backend/`)
```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install fastapi==0.115.0 "uvicorn[standard]==0.30.6" pydantic==2.9.2 python-dotenv==1.0.1 httpx==0.27.2 pytest==8.3.3
python -m pytest tests/test_gateway.py
uvicorn app.main:app --reload --port 8000
```
Swagger: http://127.0.0.1:8000/docs

## Files (Developer A)
| File | Purpose |
|---|---|
| `app/main.py` | app start-up, CORS, 400 on invalid input, `/health` |
| `app/core/config.py` | settings from environment variables |
| `app/core/logging_config.py` | logging setup |
| `app/core/security.py` | admin token check, account-number masking |
| `app/schemas/enums.py`, `app/schemas/models.py` | Pydantic request/response models, agent contract |
| `app/api/routes_decision.py` | `POST /retry-decision` |
| `app/api/routes_audit.py` | reasoning, audit, live transactions |
| `app/api/routes_admin.py` | kill switch |
| `app/services/gateway.py` | orchestration + guardrails |
| `app/db/database.py` | SQLite persistence |
| `app/agent/interface.py`, `app/agent/stub_agent.py` | agent contract + stub |
| `tests/test_gateway.py` | 21 tests |

## Request flow (`POST /retry-decision`)
1. Pydantic validation → **400** on bad input
2. Exact duplicate (same transaction_id + retry_count + payload) → stored decision, `"replayed": true`
3. **Kill switch ON** → `NO_RECOMMENDATION`, agent not called
4. **retry_count >= MAX_RETRY_COUNT** → `DONT_RETRY`, HTTP **429**, confidence 1.0, agent not called
5. Agent called with a timeout. Exception / timeout / invalid output → `NO_RECOMMENDATION`
6. Decision + reasoning steps saved in SQLite, audit event written

## Endpoints
| Method | Path | Notes |
|---|---|---|
| GET | /health | |
| POST | /retry-decision | official contract |
| GET | /transactions/{id}/recommendation | latest decision |
| GET | /transactions/{id}/reasoning | official contract: steps + tool logs |
| GET | /dashboard/transactions?limit=50 | official contract: live ticker |
| GET | /audit/{id} | audit events |
| GET | /admin/kill-switch | current state |
| POST | /admin/kill-switch | header `X-Admin-Token`, body `{"enabled": true, "reason": "...", "actor": "..."}` |

## Contract for Developer B (agent)
Create `app/agent/real_agent.py`:
```python
from ..schemas import AgentDecision, RetryRecommendationRequest

class RealAgent:
    name = "llm-agent"
    def decide(self, request: RetryRecommendationRequest) -> AgentDecision:
        ...
```
Then set `AGENT_MODE=real`. Fields of `AgentDecision` are in `app/schemas/models.py`
(`optimal_timing` required for RETRY_LATER, `correction_suggestions` required for RETRY_AFTER_UPDATE;
`steps` = Thought/Action/Observation list shown in the reasoning view).
The gateway already handles kill switch and retry budget before calling the agent.

## Database (SQLite, `app/db/database.py`)
- `recommendations` – one row per decision: request, response, reasoning steps, tool logs, latency
- `audit_events` – append-only log (decisions, replays, kill-switch changes)
- `settings` – kill-switch state (survives restarts)
