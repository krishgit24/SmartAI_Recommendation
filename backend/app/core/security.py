"""Prototype security helpers: admin-token check for state-changing endpoints, and log masking."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request


def require_admin(request: Request, x_admin_token: str = Header(default="")) -> None:
    """Rejects the call unless header X-Admin-Token matches ADMIN_TOKEN from the environment."""
    if not hmac.compare_digest(x_admin_token, request.app.state.settings.admin_token):
        raise HTTPException(status_code=401, detail="invalid or missing X-Admin-Token")


def mask(value: str | None) -> str:
    """Keep only the last 4 characters of an account number, e.g. ******************3000."""
    if not value:
        return ""
    v = value.replace(" ", "")
    if len(v) <= 8:
        return value
    return "*" * (len(v) - 4) + v[-4:]
