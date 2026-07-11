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


def test_embed_source_mutate_denied_403(client):
    with patch("api.routers.embedding.model_manager.get_embedding_model", new=AsyncMock(return_value=object())):
        with patch(
            "api.routers.embedding.require_mutate_source",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="nope")),
        ):
            resp = client.post("/api/embed", json={"item_id": "source:x", "item_type": "source"})
    assert resp.status_code == 403
