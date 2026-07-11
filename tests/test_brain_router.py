"""Tests for the GET /api/brain/graph router.

Follows the landed pattern used by tests/test_projects_api.py: override P2's
get_auth_context with a synthetic AuthContext, and mock the service layer
(api.brain_service.get_brain_graph) so no real DB is needed.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.brain_models import BrainEdge, BrainGraphResponse, BrainNode
from api.deps import get_auth_context
from api.security import AuthContext


def _ctx(role="owner", workspace_id="workspace:ws1", user_id="user:u1"):
    return AuthContext(user_id=user_id, workspace_id=workspace_id, role=role)


@pytest.fixture
def client():
    from api.main import app

    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _override(app, ctx):
    app.dependency_overrides[get_auth_context] = lambda: ctx


class TestBrainGraph:
    @patch("api.routers.brain.get_brain_graph", new_callable=AsyncMock)
    def test_get_brain_graph_returns_nodes_and_edges(self, mock_get_graph, client):
        from api.main import app

        _override(app, _ctx())
        mock_get_graph.return_value = BrainGraphResponse(
            nodes=[
                BrainNode(id="entity:d1", kind="domain", label="Engineering", salience=5.0)
            ],
            edges=[BrainEdge(source="source:s1", target="entity:d1", type="mentions")],
        )

        resp = client.get("/api/brain/graph?domain=engineering&limit=50")

        assert resp.status_code == 200
        body = resp.json()
        assert body["nodes"][0]["id"] == "entity:d1"
        assert body["edges"][0]["type"] == "mentions"

        mock_get_graph.assert_awaited_once()
        call_ctx = mock_get_graph.await_args.args[0]
        assert call_ctx.workspace_id == "workspace:ws1"
        assert mock_get_graph.await_args.kwargs["domain"] == "engineering"
        assert mock_get_graph.await_args.kwargs["limit"] == 50

    @patch("api.routers.brain.get_brain_graph", new_callable=AsyncMock)
    def test_get_brain_graph_defaults(self, mock_get_graph, client):
        from api.main import app

        _override(app, _ctx())
        mock_get_graph.return_value = BrainGraphResponse(nodes=[], edges=[])

        resp = client.get("/api/brain/graph")

        assert resp.status_code == 200
        assert resp.json() == {"nodes": [], "edges": []}
        assert mock_get_graph.await_args.kwargs["domain"] is None
        assert mock_get_graph.await_args.kwargs["limit"] == 200
