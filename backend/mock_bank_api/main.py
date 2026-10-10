
"""Deterministic mock bank status API for the Smart Recommendation project.

Run from the repository root:
    uvicorn backend.mock_bank_api.main:app --reload --port 8001

Alternatively, from the backend directory:
    uvicorn mock_bank_api.main:app --reload --port 8001

Configure failures with:
    MOCK_BANK_API_FAILURES=accounts,accounts-balance
    MOCK_BANK_API_FAILURES=all
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Mock Bank Status API",
    version="1.0.0",
    description="Deterministic simulated bank API for hackathon testing.",
)

# All records here are synthetic test data, not real bank/customer information.
ACCOUNTS: dict[str, dict[str, Any]] = {
    "10000001": {
        "exists": True,
        "status": "ACTIVE",
        "account_number": "10000001",
        "account_name": "Demo Trading Company",
        "currency": "INR",
        "account_type": "CHECKING",
    },
    "10000002": {
        "exists": True,
        "status": "FROZEN",
        "account_number": "10000002",
        "account_name": "Frozen Demo Account",
        "currency": "INR",
        "account_type": "SAVINGS",
    },
    "10000003": {
        "exists": True,
        "status": "CLOSED",
        "account_number": "10000003",
        "account_name": "Closed Demo Account",
        "currency": "INR",
        "account_type": "CHECKING",
    },
    "10000004": {
        "exists": True,
        "status": "INACTIVE",
        "account_number": "10000004",
        "account_name": "Inactive Demo Account",
        "currency": "INR",
        "account_type": "SAVINGS",
    },
}

BALANCES: dict[str, dict[str, Any]] = {
    "10000001": {"current": 125000.00, "available": 120000.00},
    "10000002": {"current": 50000.00, "available": 0.00},
    "10000003": {"current": 0.00, "available": 0.00},
    "10000004": {"current": 10000.00, "available": 10000.00},
}

BANKS: dict[str, dict[str, Any]] = {
    "DEMOINBBXXX": {
        "bic_code": "DEMOINBBXXX",
        "bank_status": "ONLINE",
        "estimated_recovery": None,
    },
    "DEMOINBB001": {
        "bic_code": "DEMOINBB001",
        "bank_status": "DEGRADED",
        "estimated_recovery": None,
    },
    "DEMOINBB002": {
        "bic_code": "DEMOINBB002",
        "bank_status": "DOWN",
        "estimated_recovery": "2026-10-10T18:00:00Z",
    },
}

VALID_ACCOUNT_STATUSES = {"ACTIVE", "INACTIVE", "FROZEN", "CLOSED"}
VALID_BANK_STATUSES = {"ONLINE", "DEGRADED", "DOWN"}


def configured_failures() -> set[str]:
    """Read failure switches each request so tests can change the environment."""
    raw = os.getenv("MOCK_BANK_API_FAILURES", "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def failure_response(endpoint: str) -> JSONResponse | None:
    failures = configured_failures()
    if "all" in failures or endpoint in failures:
        return JSONResponse(
            status_code=503,
            content={
                "error": "mock_bank_unavailable",
                "message": f"Simulated failure for {endpoint}",
            },
        )
    return None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/accounts")
def get_account(
    request: Request,
    account_number: str = Query(..., alias="account-number", min_length=1),
) -> Any:
    failed = failure_response("accounts")
    if failed:
        return failed

    number = account_number.strip().replace(" ", "")
    account = ACCOUNTS.get(number)

    if account:
        return dict(account)

    return {
        "exists": False,
        "status": "NOT_FOUND",
        "account_number": number,
        "account_name": "",
        "currency": "INR",
    }


@app.get("/api/accounts-balance")
def get_account_balance(
    account_number: str = Query(..., alias="account-number", min_length=1),
) -> Any:
    failed = failure_response("accounts-balance")
    if failed:
        return failed

    number = account_number.strip().replace(" ", "")
    if number not in ACCOUNTS:
        return JSONResponse(
            status_code=404,
            content={"error": "account_not_found", "account_number": number},
        )

    return {
        "account_number": number,
        **BALANCES[number],
        "currency": ACCOUNTS[number]["currency"],
    }


@app.get("/api/bank-status")
def get_bank_status(
    bic_code: str = Query(..., alias="bic-code", min_length=1),
) -> Any:
    failed = failure_response("bank-status")
    if failed:
        return failed

    code = bic_code.strip().upper()
    bank = BANKS.get(code)

    if bank:
        return dict(bank)

    # Unknown banks are not assumed to be online.
    return {
        "bic_code": code,
        "bank_status": "DOWN",
        "estimated_recovery": None,
    }
