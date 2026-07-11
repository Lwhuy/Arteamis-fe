from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.source_permissions import PermissionContext, get_permission_context
from open_notebook.domain.notebook import Source, SourceInsight


@pytest.fixture
def client():
    from api.main import app
    ctx = PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role="member")
    app.dependency_overrides[get_permission_context] = lambda: ctx
    yield TestClient(app)
    app.dependency_overrides.clear()


def _insight():
    return SourceInsight(id="source_insight:1", insight_type="x", content="c")


def test_get_insight_view_denied_404(client):
    with patch.object(SourceInsight, "get", new=AsyncMock(return_value=_insight())):
        with patch.object(
            SourceInsight, "get_source",
            new=AsyncMock(return_value=Source(id="source:1", title="t")),
        ):
            with patch(
                "api.routers.insights.require_view_source",
                new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
            ):
                resp = client.get("/api/insights/source_insight:1")
    assert resp.status_code == 404


def test_delete_insight_mutate_denied_403(client):
    with patch.object(SourceInsight, "get", new=AsyncMock(return_value=_insight())):
        with patch.object(
            SourceInsight, "get_source",
            new=AsyncMock(return_value=Source(id="source:1", title="t")),
        ):
            with patch(
                "api.routers.insights.require_mutate_source",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="nope")),
            ):
                resp = client.delete("/api/insights/source_insight:1")
    assert resp.status_code == 403
