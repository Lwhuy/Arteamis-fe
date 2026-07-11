from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.source_permissions import PermissionContext, get_permission_context
from open_notebook.domain.notebook import Source


@pytest.fixture
def ctx():
    return PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role="member")


@pytest.fixture
def client(ctx):
    from api.main import app

    app.dependency_overrides[get_permission_context] = lambda: ctx
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_source_view_denied_returns_404(client):
    with patch(
        "api.routers.sources.require_view_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.get("/api/sources/source:secret")
    assert resp.status_code == 404


def test_update_source_mutate_denied_returns_403(client):
    with patch(
        "api.routers.sources.require_mutate_source",
        new=AsyncMock(side_effect=HTTPException(status_code=403, detail="You do not have permission to modify this source")),
    ):
        resp = client.put("/api/sources/source:x", json={"title": "new"})
    assert resp.status_code == 403


def test_delete_source_mutate_denied_returns_403(client):
    with patch(
        "api.routers.sources.require_mutate_source",
        new=AsyncMock(side_effect=HTTPException(status_code=403, detail="nope")),
    ):
        resp = client.delete("/api/sources/source:x")
    assert resp.status_code == 403


def test_list_sources_filters_by_visible_ids(client):
    # visible_source_ids returns an empty allow-list -> no rows, and the id
    # filter param is threaded into the query.
    captured = {}

    async def fake_repo_query(q, params=None):
        captured["query"] = q
        captured["params"] = params or {}
        return []

    with patch("api.routers.sources.visible_source_ids", new=AsyncMock(return_value=[])):
        with patch("api.routers.sources.repo_query", new=fake_repo_query):
            resp = client.get("/api/sources")
    assert resp.status_code == 200
    assert resp.json() == []
    assert "visible_ids" in captured["params"]
    assert "id IN $visible_ids" in captured["query"]


def test_create_source_rejects_non_member_project(client, ctx):
    # ctx.project_role returns None -> caller is not a member of the target project -> 403
    ctx.project_role = AsyncMock(return_value=None)

    class _FakeProject:
        id = "notebook:p1"
        workspace = "workspace:w1"
        default_source_scope = "project"

    async def fake_project_get(pid):
        return _FakeProject()

    with patch(
        "api.routers.sources.Project.get", new=AsyncMock(side_effect=fake_project_get)
    ):
        resp = client.post(
            "/api/sources",
            data={"type": "text", "content": "hi", "notebooks": '["notebook:p1"]', "scope": "personal"},
        )
    assert resp.status_code == 403


def test_create_source_resolves_scope_from_project_default(client, ctx):
    # scope omitted entirely -> falls back to the target project's
    # default_source_scope ("company" in this fixture project).
    ctx.project_role = AsyncMock(return_value="member")
    captured = {}

    class _FakeProject:
        id = "notebook:p1"
        workspace = "workspace:w1"
        default_source_scope = "company"

    async def fake_project_get(pid):
        return _FakeProject()

    async def fake_save(self):
        captured["scope"] = self.scope
        self.id = "source:fake"
        return self

    with patch("api.routers.sources.Project.get", new=AsyncMock(side_effect=fake_project_get)):
        with patch.object(Source, "save", new=fake_save):
            with patch.object(Source, "add_to_notebook", new=AsyncMock()):
                with patch(
                    "api.routers.sources.CommandService.submit_command_job",
                    new=AsyncMock(return_value="command:123"),
                ):
                    # async_processing=true keeps this test off the sync
                    # execute_command_sync path, which drives the real
                    # source-processing pipeline against a live DB - out of
                    # scope for this unit test, which only asserts scope
                    # resolution + owner/scope stamping on create.
                    resp = client.post(
                        "/api/sources",
                        data={
                            "type": "text",
                            "content": "hi",
                            "notebooks": '["notebook:p1"]',
                            "async_processing": "true",
                        },
                    )
    assert resp.status_code in (200, 201, 202)
    assert captured.get("scope") == "company"
