from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from surrealdb import RecordID

from api.source_permissions import PermissionContext, get_permission_context


@pytest.mark.asyncio
async def test_text_search_passes_viewer_source_ids_to_fn():
    captured = {}

    async def fake_repo_query(q, params=None):
        captured["q"] = q
        captured["params"] = params or {}
        return []

    from open_notebook.domain.notebook import text_search
    with patch("open_notebook.domain.notebook.repo_query", new=fake_repo_query):
        await text_search("hello", 10, True, True, viewer_source_ids=["source:a"])
    assert "fn::text_search" in captured["q"]
    assert "$viewer_source_ids" in captured["q"]
    assert isinstance(captured["params"]["viewer_source_ids"][0], RecordID)


@pytest.mark.asyncio
async def test_vector_search_passes_viewer_source_ids_to_fn():
    captured = {}

    async def fake_repo_query(q, params=None):
        captured["params"] = params or {}
        return []

    from open_notebook.domain import notebook as nb
    with patch("open_notebook.domain.notebook.repo_query", new=fake_repo_query):
        with patch("open_notebook.utils.embedding.generate_embedding", new=AsyncMock(return_value=[0.1, 0.2])):
            await nb.vector_search("hello", 10, True, True, viewer_source_ids=["source:b"])
    assert "viewer_source_ids" in captured["params"]
    assert str(captured["params"]["viewer_source_ids"][0]) == "source:b"


def test_search_endpoint_computes_and_forwards_viewer_ids():
    from api.main import app
    ctx = PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role="member")
    app.dependency_overrides[get_permission_context] = lambda: ctx
    try:
        client = TestClient(app)
        with patch("api.routers.search.visible_source_ids", new=AsyncMock(return_value=["source:a"])) as vsi:
            with patch("api.routers.search.text_search", new=AsyncMock(return_value=[])) as ts:
                resp = client.post("/api/search", json={"query": "q", "type": "text", "limit": 5, "search_sources": True, "search_notes": True})
        assert resp.status_code == 200
        vsi.assert_awaited()
        assert ts.await_args.kwargs["viewer_source_ids"] == ["source:a"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ask_graph_provide_answer_uses_configurable_viewer_ids():
    from open_notebook.graphs.ask import provide_answer
    captured = {}

    async def fake_vector_search(term, n, s, note, **kw):
        captured["kw"] = kw
        return []

    with patch("open_notebook.graphs.ask.vector_search", new=fake_vector_search):
        await provide_answer(
            {"question": "q", "term": "t", "instructions": "i"},
            {"configurable": {"answer_model": "m", "viewer_source_ids": ["source:a"]}},
        )
    assert captured["kw"]["viewer_source_ids"] == ["source:a"]
