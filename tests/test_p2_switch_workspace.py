"""API tests for POST /auth/switch-workspace/{workspace_id}."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.security import create_identity_token, decode_access_token
from open_notebook.domain.workspace import Membership


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    # Function-scoped and auto-reverted so this test's JWT_SECRET never leaks
    # into other test modules (see tests/test_p2_workspaces_router.py and
    # tests/test_p2_access_token.py for the same pattern). Deviation from the
    # brief's module-level os.environ.setdefault(...): that pollutes the whole
    # test session (env vars set at import time are never unset), which broke
    # ~74 unrelated tests when the full suite ran in the same process.
    monkeypatch.setenv("JWT_SECRET", "test-secret-p2-switch")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def _auth(user_id: str = "user:1") -> dict:
    return {"Authorization": f"Bearer {create_identity_token(user_id)}"}


@patch("api.routers.auth.get_membership", new_callable=AsyncMock)
def test_switch_workspace_member_gets_scoped_token(mock_get, client):
    mock_get.return_value = Membership(
        id="membership:1",
        user="user:1",
        workspace="workspace:acme",
        role="member",
        status="active",
    )
    resp = client.post("/api/auth/switch-workspace/workspace:acme", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_workspace_id"] == "workspace:acme"
    assert body["role"] == "member"
    ctx = decode_access_token(body["access_token"])
    assert ctx.workspace_id == "workspace:acme"
    assert ctx.role == "member"


@patch("api.routers.auth.get_membership", new_callable=AsyncMock)
def test_switch_to_own_personal_workspace_works_like_any_other(mock_get, client):
    mock_get.return_value = Membership(
        id="membership:0",
        user="user:1",
        workspace="workspace:p1",
        role="owner",
        status="active",
    )
    resp = client.post("/api/auth/switch-workspace/workspace:p1", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["role"] == "owner"


@patch("api.routers.auth.get_membership", new_callable=AsyncMock)
def test_switch_workspace_non_member_403(mock_get, client):
    mock_get.return_value = None
    resp = client.post("/api/auth/switch-workspace/workspace:other", headers=_auth())
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not a member of this workspace"


@patch("api.routers.auth.get_membership", new_callable=AsyncMock)
def test_switch_workspace_revoked_membership_403(mock_get, client):
    mock_get.return_value = Membership(
        id="membership:1",
        user="user:1",
        workspace="workspace:acme",
        role="member",
        status="revoked",
    )
    resp = client.post("/api/auth/switch-workspace/workspace:acme", headers=_auth())
    assert resp.status_code == 403


def test_switch_workspace_requires_auth(client):
    assert client.post("/api/auth/switch-workspace/workspace:acme").status_code == 401
