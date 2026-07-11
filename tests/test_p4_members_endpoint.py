from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.security import AuthContext


@pytest.fixture
def app():
    from api.main import app as fastapi_app

    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


def test_members_list_for_member(app):
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id="user:m", workspace_id="workspace:acme", role="member"
    )
    with patch("api.routers.invitations.workspace_service.list_members", new_callable=AsyncMock) as lm:
        lm.return_value = [
            {"user_id": "user:1", "email": "a@x.com", "display_name": "A", "role": "owner", "status": "active"}
        ]
        client = TestClient(app)
        resp = client.get("/api/workspaces/workspace:acme/members")
    assert resp.status_code == 200
    assert resp.json()[0]["role"] == "owner"


def test_members_cross_workspace_404(app):
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id="user:m", workspace_id="workspace:acme", role="member"
    )
    client = TestClient(app)
    assert client.get("/api/workspaces/workspace:other/members").status_code == 404
