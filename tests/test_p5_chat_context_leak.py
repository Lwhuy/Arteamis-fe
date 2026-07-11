"""P5 fix: POST /api/chat/context (build_context) must not leak source content
across visibility scopes/workspaces. This is the chat.py twin of the leak
already fixed in api/routers/context.py::get_notebook_context (P5 Task 11) --
same fix, same test shape: mirror api/source_permissions.visible_source_ids
into both the explicit-source-id branch and the default (no context_config)
branch.

P6 rollout: build_context now also requires CtxDep (repo.get(notebook_id) is
workspace-checked before visible_source_ids runs at all) -- these tests
override get_auth_context alongside get_permission_context and patch
open_notebook.database.scoping.repo_query for the ownership check, and patch
api.routers.chat.Project (not Notebook.get, which no longer exists here) so
the mocked notebook object is used regardless of the raw row content.
"""
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from api.deps import get_auth_context
from api.security import AuthContext
from api.source_permissions import PermissionContext, get_permission_context


@pytest.fixture
def client():
    from api.main import app

    ctx = PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role="member")
    app.dependency_overrides[get_permission_context] = lambda: ctx
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id="user:u1", workspace_id="workspace:w1", role="member"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _mock_notebook():
    notebook = Mock()
    notebook.get_sources = AsyncMock(return_value=[])
    notebook.get_notes = AsyncMock(return_value=[])
    return notebook


def _patched_repo_get(row=None):
    """Patch the scoping module's repo_query so repo.get(notebook_id) returns
    a row (or 404s if row=None, simulating a cross-workspace notebook_id)."""
    return patch(
        "open_notebook.database.scoping.repo_query",
        new=AsyncMock(return_value=[row] if row else []),
    )


def test_explicit_branch_denies_source_not_in_visible_set(client):
    """Caller lists an id they cannot view alongside one they can. Only the
    visible one's content may come back, and the source-fetch raw query must
    not even run for the denied id (belt-and-braces, matching context.py)."""
    notebook = _mock_notebook()

    visible_source = Mock()
    visible_source.get_context = AsyncMock(return_value={"id": "source:a", "content": "AAA"})

    # repo_query call sequence: 1) repo.get(notebook_id) ownership check,
    # 2) build_context's repo.raw() fetch of the one visible source (source:b
    # is filtered out by the `visible` set before any raw call is attempted).
    scoped_q = AsyncMock(
        side_effect=[
            [{"id": "notebook:n1", "workspace": "workspace:w1"}],
            [{"id": "source:a"}],
        ]
    )

    with patch("open_notebook.database.scoping.repo_query", new=scoped_q):
        with patch("api.routers.chat.Project", return_value=notebook):
            with patch("api.routers.chat.visible_source_ids", new=AsyncMock(return_value=["source:a"])):
                with patch("api.routers.chat.Source", return_value=visible_source):
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
    # Denied id must be filtered out before the raw source-fetch is even
    # attempted: only 2 repo_query calls total (ownership check + source:a).
    assert scoped_q.await_count == 2


def test_default_branch_passes_viewer_source_ids_to_get_sources(client):
    """No context_config -> default branch must scope notebook.get_sources()
    to the caller's visible set instead of returning every source."""
    notebook = _mock_notebook()

    with _patched_repo_get({"id": "notebook:n1", "workspace": "workspace:w1"}):
        with patch("api.routers.chat.Project", return_value=notebook):
            with patch("api.routers.chat.visible_source_ids", new=AsyncMock(return_value=["source:a"])):
                with patch("api.routers.chat.SourceInsight.get_for_sources", new=AsyncMock(return_value={})):
                    resp = client.post(
                        "/api/chat/context",
                        json={"notebook_id": "notebook:n1", "context_config": {}},
                    )

    assert resp.status_code == 200
    notebook.get_sources.assert_awaited()
    assert notebook.get_sources.await_args.kwargs.get("viewer_source_ids") == {"source:a"}


def test_cross_workspace_notebook_id_404s_before_any_source_lookup():
    """P6 rollout: a notebook_id belonging to another workspace now 404s at
    the repo.get() ownership check, before visible_source_ids or any source
    lookup ever runs -- strictly tighter than the pre-P6 behavior (which
    fetched the notebook unscoped and relied solely on visible_source_ids
    returning an empty set)."""
    from api.main import app

    app.dependency_overrides[get_permission_context] = lambda: PermissionContext(
        user_id="user:u1", workspace_id="workspace:w1", workspace_role="member"
    )
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id="user:u1", workspace_id="workspace:w1", role="member"
    )
    client = TestClient(app)
    try:
        with _patched_repo_get(None):  # repo.get() ownership check finds nothing
            resp = client.post(
                "/api/chat/context",
                json={"notebook_id": "notebook:other-ws", "context_config": {}},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
