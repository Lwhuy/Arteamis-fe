"""P5 fix: POST /api/chat/context (build_context) must not leak source content
across visibility scopes/workspaces. This is the chat.py twin of the leak
already fixed in api/routers/context.py::get_notebook_context (P5 Task 11) --
same fix, same test shape: mirror api/source_permissions.visible_source_ids
into both the explicit-source-id branch and the default (no context_config)
branch.
"""
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from api.source_permissions import PermissionContext, get_permission_context


@pytest.fixture
def client():
    from api.main import app

    ctx = PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role="member")
    app.dependency_overrides[get_permission_context] = lambda: ctx
    yield TestClient(app)
    app.dependency_overrides.clear()


def _mock_notebook():
    notebook = Mock()
    notebook.get_sources = AsyncMock(return_value=[])
    notebook.get_notes = AsyncMock(return_value=[])
    return notebook


def test_explicit_branch_denies_source_not_in_visible_set(client):
    """Caller lists an id they cannot view alongside one they can. Only the
    visible one's content may come back, and Source.get must not even be
    called for the denied id (belt-and-braces, matching context.py)."""
    notebook = _mock_notebook()

    visible_source = Mock()
    visible_source.get_context = AsyncMock(return_value={"id": "source:a", "content": "AAA"})

    denied_source_get = AsyncMock(return_value=Mock(get_context=AsyncMock(return_value={"id": "source:b", "content": "SECRET-B"})))

    async def fake_source_get(full_id):
        if full_id == "source:a":
            return visible_source
        # Should never be reached for a denied id.
        return await denied_source_get(full_id)

    with patch("api.routers.chat.Notebook.get", new=AsyncMock(return_value=notebook)):
        with patch("api.routers.chat.visible_source_ids", new=AsyncMock(return_value=["source:a"])):
            with patch("api.routers.chat.Source.get", new=AsyncMock(side_effect=fake_source_get)) as src_get:
                resp = client.post(
                    "/api/chat/context",
                    json={
                        "notebook_id": "notebook:n1",
                        "context_config": {
                            "sources": {
                                "source:a": "full content",
                                "source:b": "full content",
                            },
                            "notes": {},
                        },
                    },
                )

    assert resp.status_code == 200
    body = resp.json()
    contents = [s.get("content") for s in body["context"]["sources"]]
    assert "AAA" in contents
    assert "SECRET-B" not in contents
    # Denied id must be filtered out before Source.get is even attempted.
    called_ids = [c.args[0] for c in src_get.await_args_list]
    assert "source:b" not in called_ids


def test_default_branch_passes_viewer_source_ids_to_get_sources(client):
    """No context_config -> default branch must scope notebook.get_sources()
    to the caller's visible set instead of returning every source."""
    notebook = _mock_notebook()

    with patch("api.routers.chat.Notebook.get", new=AsyncMock(return_value=notebook)):
        with patch("api.routers.chat.visible_source_ids", new=AsyncMock(return_value=["source:a"])):
            with patch("api.routers.chat.SourceInsight.get_for_sources", new=AsyncMock(return_value={})):
                resp = client.post(
                    "/api/chat/context",
                    json={"notebook_id": "notebook:n1", "context_config": {}},
                )

    assert resp.status_code == 200
    notebook.get_sources.assert_awaited()
    assert notebook.get_sources.await_args.kwargs.get("viewer_source_ids") == {"source:a"}


def test_cross_workspace_notebook_yields_no_sources_either_branch(client):
    """A notebook_id belonging to another workspace must resolve to an empty
    visible set (this is what api.source_permissions.visible_source_ids
    guarantees via its workspace-scoped query) -- and build_context must
    honor that emptiness in BOTH branches, not just fetch everything."""
    notebook = _mock_notebook()

    # Simulate get_sources() actually respecting the (empty) filter, the way
    # Notebook.get_sources's real implementation does.
    all_sources = [Mock(id="source:a"), Mock(id="source:b")]

    async def fake_get_sources(viewer_source_ids=None, include_full_text=False):
        if viewer_source_ids is None:
            return all_sources
        allowed = set(viewer_source_ids)
        return [s for s in all_sources if s.id in allowed]

    notebook.get_sources = AsyncMock(side_effect=fake_get_sources)

    with patch("api.routers.chat.Notebook.get", new=AsyncMock(return_value=notebook)):
        with patch("api.routers.chat.visible_source_ids", new=AsyncMock(return_value=[])):
            with patch("api.routers.chat.SourceInsight.get_for_sources", new=AsyncMock(return_value={})):
                # Default branch.
                resp_default = client.post(
                    "/api/chat/context",
                    json={"notebook_id": "notebook:other-ws", "context_config": {}},
                )
                # Explicit-id branch, requesting ids that exist but belong to
                # another workspace (not in the empty visible set).
                with patch("api.routers.chat.Source.get", new=AsyncMock()) as src_get:
                    resp_explicit = client.post(
                        "/api/chat/context",
                        json={
                            "notebook_id": "notebook:other-ws",
                            "context_config": {
                                "sources": {"source:a": "full content"},
                                "notes": {},
                            },
                        },
                    )

    assert resp_default.status_code == 200
    assert resp_default.json()["context"]["sources"] == []

    assert resp_explicit.status_code == 200
    assert resp_explicit.json()["context"]["sources"] == []
    src_get.assert_not_awaited()
