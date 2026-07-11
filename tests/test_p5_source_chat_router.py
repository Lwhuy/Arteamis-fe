from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.source_permissions import PermissionContext, get_permission_context


@pytest.fixture
def client():
    from api.main import app

    ctx = PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role="member")
    app.dependency_overrides[get_permission_context] = lambda: ctx
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_session_view_denied_404(client):
    with patch(
        "api.routers.source_chat.require_view_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.post("/api/sources/source:secret/chat/sessions", json={"source_id": "source:secret"})
    assert resp.status_code == 404


def test_list_sessions_view_denied_404(client):
    with patch(
        "api.routers.source_chat.require_view_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.get("/api/sources/source:secret/chat/sessions")
    assert resp.status_code == 404
