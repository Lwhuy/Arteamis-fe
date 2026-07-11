"""API tests for POST/GET /workspaces (service + token minting exercised)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.security import create_identity_token, decode_access_token
from open_notebook.domain.workspace import Membership, Workspace
from open_notebook.exceptions import DuplicateResourceError


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    # Function-scoped and auto-reverted so this test's JWT_SECRET never leaks
    # into other test modules (see tests/test_p2_deps.py for the same
    # pattern). Deviation from the brief's module-level
    # os.environ.setdefault(...): that pollutes the whole test session (env
    # vars set at import time are never unset), which broke ~74 unrelated
    # tests when the full suite ran in the same process.
    monkeypatch.setenv("JWT_SECRET", "test-secret-p2-router")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def _auth(user_id: str = "user:1") -> dict:
    return {"Authorization": f"Bearer {create_identity_token(user_id)}"}


@patch("api.routers.workspaces.create_workspace", new_callable=AsyncMock)
def test_create_workspace_returns_owner_token(mock_create, client):
    workspace = Workspace(id="workspace:acme", name="Acme", slug="acme", kind="company", owner="user:1")
    membership = Membership(
        id="membership:1", user="user:1", workspace="workspace:acme", role="owner"
    )
    mock_create.return_value = (workspace, membership)

    resp = client.post("/api/workspaces", json={"name": "Acme"}, headers=_auth())

    assert resp.status_code == 201
    body = resp.json()
    assert body["active_workspace_id"] == "workspace:acme"
    assert body["role"] == "owner"
    ctx = decode_access_token(body["access_token"])
    assert ctx.user_id == "user:1"
    assert ctx.workspace_id == "workspace:acme"
    assert ctx.role == "owner"
    mock_create.assert_awaited_once_with("user:1", "Acme", None)


@patch("api.routers.workspaces.create_workspace", new_callable=AsyncMock)
def test_create_workspace_slug_conflict_returns_409(mock_create, client):
    mock_create.side_effect = DuplicateResourceError("Workspace slug already exists")
    resp = client.post("/api/workspaces", json={"name": "Acme"}, headers=_auth())
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Workspace slug already exists"


def test_create_workspace_requires_auth(client):
    assert client.post("/api/workspaces", json={"name": "Acme"}).status_code == 401


def test_create_workspace_empty_name_422(client):
    resp = client.post("/api/workspaces", json={"name": ""}, headers=_auth())
    assert resp.status_code == 422


def test_create_workspace_body_has_no_kind_field(client):
    # A client CANNOT request kind="personal" — the schema has no such field, so
    # an extra "kind" in the body is silently ignored by Pydantic (not an error),
    # and the service always creates kind="company" regardless.
    with patch("api.routers.workspaces.create_workspace", new_callable=AsyncMock) as mock_create:
        workspace = Workspace(id="workspace:x", name="X", slug="x", kind="company", owner="user:1")
        membership = Membership(id="membership:1", user="user:1", workspace="workspace:x", role="owner")
        mock_create.return_value = (workspace, membership)
        resp = client.post(
            "/api/workspaces", json={"name": "X", "kind": "personal"}, headers=_auth()
        )
    assert resp.status_code == 201
    mock_create.assert_awaited_once_with("user:1", "X", None)  # "kind" was ignored


@patch("api.routers.workspaces.list_memberships", new_callable=AsyncMock)
def test_list_workspaces_returns_only_callers_memberships(mock_list, client):
    mock_list.return_value = [
        {
            "workspace_id": "workspace:p1",
            "name": "Personal",
            "slug": "personal-1",
            "kind": "personal",
            "role": "owner",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }
    ]
    resp = client.get("/api/workspaces", headers=_auth())
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "id": "workspace:p1",
            "name": "Personal",
            "slug": "personal-1",
            "kind": "personal",
            "role": "owner",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }
    ]
    mock_list.assert_awaited_once_with("user:1")


@patch("api.routers.workspaces.list_memberships", new_callable=AsyncMock)
def test_list_workspaces_never_empty_for_authenticated_user(mock_list, client):
    # Contrast with the superseded company-only draft: an authenticated user
    # always has at least their personal workspace.
    mock_list.return_value = [
        {"workspace_id": "workspace:p1", "name": "Personal", "slug": "personal-1", "kind": "personal", "role": "owner", "created": "", "updated": ""}
    ]
    resp = client.get("/api/workspaces", headers=_auth())
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["kind"] == "personal"
