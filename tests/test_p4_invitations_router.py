from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import deps
from api.security import AuthContext


def _owner_ctx():
    return AuthContext(user_id="user:owner", workspace_id="workspace:acme", role="owner")


def _member_ctx():
    return AuthContext(user_id="user:m", workspace_id="workspace:acme", role="member")


@pytest.fixture
def app():
    from api.main import app as fastapi_app

    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


def _fake_inv(**over):
    from datetime import datetime, timedelta, timezone

    from open_notebook.domain.invitation import Invitation

    base = dict(
        id="invitation:1",
        workspace="workspace:acme",
        email="alice@example.com",
        role="member",
        project=None,
        token_hash="h",
        status="pending",
        invited_by="user:owner",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    base.update(over)
    return Invitation(**base)


def test_create_invite_owner_returns_share_url_when_email_not_sent(app):
    app.dependency_overrides[deps.get_auth_context] = _owner_ctx
    with patch("api.routers.invitations.invitation_service.create_invitation", new_callable=AsyncMock) as create, \
         patch("api.routers.invitations.invitation_service.build_invite_url", return_value="http://localhost:3000/invite/RAW"), \
         patch("api.routers.invitations.email_service.send_invite_email", new_callable=AsyncMock) as send, \
         patch("api.routers.invitations._project_name", new_callable=AsyncMock) as pname:
        create.return_value = (_fake_inv(), "RAW")
        send.return_value = False  # console provider -> not delivered
        pname.return_value = None
        client = TestClient(app)
        resp = client.post(
            "/api/workspaces/workspace:acme/invitations",
            json={"email": "alice@example.com", "role": "member"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email_sent"] is False
    assert body["share_url"] == "http://localhost:3000/invite/RAW"
    assert body["invitation"]["status"] == "pending"


def test_create_invite_email_sent_hides_share_url(app):
    app.dependency_overrides[deps.get_auth_context] = _owner_ctx
    with patch("api.routers.invitations.invitation_service.create_invitation", new_callable=AsyncMock) as create, \
         patch("api.routers.invitations.invitation_service.build_invite_url", return_value="http://x/invite/RAW"), \
         patch("api.routers.invitations.email_service.send_invite_email", new_callable=AsyncMock) as send, \
         patch("api.routers.invitations._project_name", new_callable=AsyncMock) as pname:
        create.return_value = (_fake_inv(), "RAW")
        send.return_value = True
        pname.return_value = None
        client = TestClient(app)
        resp = client.post(
            "/api/workspaces/workspace:acme/invitations",
            json={"email": "alice@example.com", "role": "member"},
        )
    assert resp.status_code == 201
    assert resp.json()["email_sent"] is True
    assert resp.json()["share_url"] is None


def test_create_invite_member_role_forbidden(app):
    # require_role("owner","admin") must 403 a workspace member.
    app.dependency_overrides[deps.get_auth_context] = _member_ctx
    client = TestClient(app)
    resp = client.post(
        "/api/workspaces/workspace:acme/invitations",
        json={"email": "a@x.com", "role": "member"},
    )
    assert resp.status_code == 403


def test_create_invite_into_personal_workspace_403(app):
    # RBAC passes (owner), but the service-level personal-workspace guard still 403s.
    app.dependency_overrides[deps.get_auth_context] = _owner_ctx
    with patch(
        "api.routers.invitations.invitation_service.create_invitation", new_callable=AsyncMock
    ) as create:
        create.side_effect = HTTPException(
            status_code=403, detail="Cannot invite members into a personal workspace"
        )
        client = TestClient(app)
        resp = client.post(
            "/api/workspaces/workspace:acme/invitations",
            json={"email": "a@x.com", "role": "member"},
        )
    assert resp.status_code == 403
    assert "personal workspace" in resp.json()["detail"]


def test_create_invite_cross_workspace_404(app):
    app.dependency_overrides[deps.get_auth_context] = _owner_ctx  # scoped to workspace:acme
    client = TestClient(app)
    resp = client.post(
        "/api/workspaces/workspace:other/invitations",
        json={"email": "a@x.com", "role": "member"},
    )
    assert resp.status_code == 404  # token's workspace != path workspace


def test_list_invites_owner(app):
    app.dependency_overrides[deps.get_auth_context] = _owner_ctx
    with patch("api.routers.invitations.invitation_service.list_invitations", new_callable=AsyncMock) as lst, \
         patch("api.routers.invitations._project_name", new_callable=AsyncMock) as pname:
        lst.return_value = [_fake_inv()]
        pname.return_value = None
        client = TestClient(app)
        resp = client.get("/api/workspaces/workspace:acme/invitations?status=pending")
    assert resp.status_code == 200
    assert resp.json()[0]["email"] == "alice@example.com"


def test_revoke_invite_owner(app):
    app.dependency_overrides[deps.get_auth_context] = _owner_ctx
    with patch("api.routers.invitations.invitation_service.revoke_invitation", new_callable=AsyncMock) as rev, \
         patch("api.routers.invitations._project_name", new_callable=AsyncMock) as pname:
        rev.return_value = _fake_inv(status="revoked")
        pname.return_value = None
        client = TestClient(app)
        resp = client.post("/api/workspaces/workspace:acme/invitations/invitation:1/revoke")
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"


def test_preview_is_public_and_returns_no_secrets(app):
    with patch("api.routers.invitations.invitation_service.preview_invitation", new_callable=AsyncMock) as prev:
        prev.return_value = {
            "workspace_name": "Acme",
            "role": "member",
            "email": "alice@example.com",
            "project_name": None,
            "status": "pending",
            "expired": False,
        }
        client = TestClient(app)
        resp = client.get("/api/invitations/RAWTOKEN")
    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace_name"] == "Acme"
    assert "token_hash" not in body and "invited_by" not in body


def test_preview_expired_410(app):
    with patch("api.routers.invitations.invitation_service.preview_invitation", new_callable=AsyncMock) as prev:
        prev.side_effect = HTTPException(status_code=410, detail="This invitation is no longer valid")
        client = TestClient(app)
        resp = client.get("/api/invitations/RAWTOKEN")
    assert resp.status_code == 410


def test_accept_as_identity_user(app):
    app.dependency_overrides[deps.get_identity] = lambda: "user:alice"
    with patch("api.routers.invitations.invitation_service.accept_invitation", new_callable=AsyncMock) as acc:
        acc.return_value = {
            "workspace_id": "workspace:acme",
            "role": "member",
            "project_id": None,
            "membership_status": "active",
        }
        client = TestClient(app)
        resp = client.post("/api/invitations/RAWTOKEN/accept")
    assert resp.status_code == 200
    assert resp.json() == {
        "workspace_id": "workspace:acme",
        "role": "member",
        "project_id": None,
        "membership_status": "active",
    }
    acc.assert_awaited_once_with("RAWTOKEN", "user:alice")
