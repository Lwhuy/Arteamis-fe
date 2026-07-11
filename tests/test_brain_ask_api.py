"""Tests for the POST /api/brain/ask SSE route.

Unlike the other /brain routes (which still use P2's get_auth_context / plain
AuthContext), /brain/ask needs the viewer_source_ids allow-list computed by
visible_source_ids(), so it depends on api.source_permissions'
PermissionContext / get_permission_context -- the same pattern used by
api/routers/search.py and tests/test_search_api.py. The service layer
(api.brain_service.ask_brain) is mocked so no real DB or model provider is
needed.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.brain_models import BrainAskEvent
from api.source_permissions import PermissionContext, get_permission_context


def _ctx(role="owner", workspace_id="workspace:ws1", user_id="user:u1"):
    return PermissionContext(user_id=user_id, workspace_id=workspace_id, workspace_role=role)


@pytest.fixture
def client():
    from api.main import app

    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _override(app, ctx):
    app.dependency_overrides[get_permission_context] = lambda: ctx


def _body():
    return {
        "question": "q?",
        "strategy_model": "model:s",
        "answer_model": "model:a",
        "final_answer_model": "model:f",
    }


async def _one_answer_event(*args, **kwargs):
    yield BrainAskEvent(type="answer", content="A", cited_node_ids=["source:a"])
    yield BrainAskEvent(type="complete", final_answer="A", cited_node_ids=["source:a"])


class TestBrainAsk:
    def test_brain_ask_streams_events_with_cited_node_ids(self, client):
        from api.main import app

        _override(app, _ctx())
        with (
            patch("api.routers.brain.Model.get", new_callable=AsyncMock, return_value=object()),
            patch(
                "api.routers.brain.model_manager.get_embedding_model",
                new_callable=AsyncMock,
                return_value=object(),
            ),
            patch("api.routers.brain.ask_brain", _one_answer_event),
        ):
            resp = client.post("/api/brain/ask", json=_body())

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.text
        assert '"type":"answer"' in body or '"type": "answer"' in body
        assert '"source:a"' in body
        assert "cited_node_ids" in body
        assert '"type":"complete"' in body or '"type": "complete"' in body

    def test_brain_ask_reads_graph_scoped_to_caller_workspace(self, client):
        from api.main import app

        _override(app, _ctx(workspace_id="workspace:alpha"))
        captured = {}

        async def _spy_ask_brain(ctx, *args, **kwargs):
            captured["workspace_id"] = ctx.workspace_id
            yield BrainAskEvent(type="complete", final_answer="ok", cited_node_ids=[])

        with (
            patch("api.routers.brain.Model.get", new_callable=AsyncMock, return_value=object()),
            patch(
                "api.routers.brain.model_manager.get_embedding_model",
                new_callable=AsyncMock,
                return_value=object(),
            ),
            patch("api.routers.brain.ask_brain", _spy_ask_brain),
        ):
            resp = client.post("/api/brain/ask", json=_body())

        assert resp.status_code == 200
        # The overridden context is workspace:alpha -- ask_brain must be scoped
        # to it, never to another workspace. Extends the P6 tenant-leakage
        # guarantee to /brain/ask.
        assert captured["workspace_id"] == "workspace:alpha"

    def test_brain_ask_missing_model_returns_400(self, client):
        from api.main import app

        _override(app, _ctx())
        with (
            patch("api.routers.brain.Model.get", new_callable=AsyncMock, return_value=None),
            patch(
                "api.routers.brain.model_manager.get_embedding_model",
                new_callable=AsyncMock,
                return_value=object(),
            ),
        ):
            resp = client.post("/api/brain/ask", json=_body())
        assert resp.status_code == 400

    def test_brain_ask_missing_embedding_model_returns_400(self, client):
        from api.main import app

        _override(app, _ctx())
        with (
            patch("api.routers.brain.Model.get", new_callable=AsyncMock, return_value=object()),
            patch(
                "api.routers.brain.model_manager.get_embedding_model",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = client.post("/api/brain/ask", json=_body())
        assert resp.status_code == 400
