import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_PATH"] = ":memory:"  # keeps the module-level app off the real DB file

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

ADMIN = {"X-Admin-Token": "test-admin-token"}


@pytest.fixture
def make_client(tmp_path):
    def _make(agent=None, **overrides):
        s = Settings()
        s.database_path = str(tmp_path / "test.db")
        s.admin_token = "test-admin-token"
        s.agent_mode = "stub"
        for k, v in overrides.items():
            setattr(s, k, v)
        return TestClient(create_app(s, agent=agent))
    return _make


@pytest.fixture
def client(make_client):
    return make_client()


def base_request(**changes) -> dict:
    req = {
        "transaction_id": "TXN-TEST-1",
        "amount": 1500.5,
        "currency": "USD",
        "payment_rail": "RTGS",
        "failure_code": "NETWORK_TIMEOUT",
        "failure_reason": "Connection timed out during handshake",
        "ordering_customer": {"name": "Globex Manufacturing Ltd", "account_number": "DE02120300000000202051",
                              "bic_code": "COBADEFFXXX"},
        "beneficiary": {"name": "Test Account Holder", "account_number": "DE89370400440532013000",
                        "bic_code": "DEUTDEFF"},
        "timestamp": "2026-09-26T10:00:00Z",
        "retry_count": 1,
    }
    for k, v in changes.items():
        if k in ("beneficiary", "ordering_customer"):
            req[k] = {**req[k], **v}
        else:
            req[k] = v
    return req
