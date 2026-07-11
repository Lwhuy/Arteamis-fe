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


def _fake_source(owner="user:owner", scope="personal", sid="source:x"):
    return Source(id=sid, title="orig title", owner=owner, scope=scope)


def test_update_source_scope_change_denied_for_non_owner_non_workspace_admin(client, ctx):
    # ctx = user:u1, workspace_role="member" -- stands in for a project-admin:
    # require_mutate_source already lets project-admins through the general
    # mutate gate, but they must NOT be able to widen/narrow scope.
    src = _fake_source(owner="user:owner", scope="personal")
    with patch("api.routers.sources.require_mutate_source", new=AsyncMock(return_value=src)):
        resp = client.put("/api/sources/source:x", json={"scope": "company"})
    assert resp.status_code == 403


def test_update_source_scope_change_allowed_for_owner(client, ctx):
    src = _fake_source(owner=ctx.user_id, scope="personal")

    async def fake_save(self):
        return self

    with patch("api.routers.sources.require_mutate_source", new=AsyncMock(return_value=src)):
        with patch.object(Source, "save", new=fake_save):
            with patch.object(Source, "get_embedded_chunks", new=AsyncMock(return_value=0)):
                resp = client.put("/api/sources/source:x", json={"scope": "company"})
    assert resp.status_code == 200
    assert resp.json()["scope"] == "company"


def test_update_source_scope_change_allowed_for_workspace_admin(client, ctx):
    ctx.workspace_role = "admin"
    src = _fake_source(owner="user:someone-else", scope="personal")

    async def fake_save(self):
        return self

    with patch("api.routers.sources.require_mutate_source", new=AsyncMock(return_value=src)):
        with patch.object(Source, "save", new=fake_save):
            with patch.object(Source, "get_embedded_chunks", new=AsyncMock(return_value=0)):
                resp = client.put("/api/sources/source:x", json={"scope": "company"})
    assert resp.status_code == 200
    assert resp.json()["scope"] == "company"


def test_update_source_non_scope_field_allowed_for_project_admin(client, ctx):
    # A project-admin (not owner, not workspace owner/admin) may still update
    # OTHER fields like title -- only the scope change itself is restricted.
    src = _fake_source(owner="user:owner", scope="personal")

    async def fake_save(self):
        return self

    with patch("api.routers.sources.require_mutate_source", new=AsyncMock(return_value=src)):
        with patch.object(Source, "save", new=fake_save):
            with patch.object(Source, "get_embedded_chunks", new=AsyncMock(return_value=0)):
                resp = client.put("/api/sources/source:x", json={"title": "new title"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "new title"


def test_update_source_scope_unchanged_allowed_for_project_admin(client, ctx):
    # Sending the SAME scope back is not a "change" -- no extra authorization
    # should be required beyond the general mutate gate.
    src = _fake_source(owner="user:owner", scope="company")

    async def fake_save(self):
        return self

    with patch("api.routers.sources.require_mutate_source", new=AsyncMock(return_value=src)):
        with patch.object(Source, "save", new=fake_save):
            with patch.object(Source, "get_embedded_chunks", new=AsyncMock(return_value=0)):
                resp = client.put("/api/sources/source:x", json={"scope": "company"})
    assert resp.status_code == 200


def test_check_source_file_view_denied_returns_404(client):
    with patch(
        "api.routers.sources.require_view_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.head("/api/sources/source:secret/download")
    assert resp.status_code == 404


def test_download_source_file_view_denied_returns_404(client):
    with patch(
        "api.routers.sources.require_view_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.get("/api/sources/source:secret/download")
    assert resp.status_code == 404


def test_get_source_status_view_denied_returns_404(client):
    with patch(
        "api.routers.sources.require_view_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.get("/api/sources/source:secret/status")
    assert resp.status_code == 404


def test_get_source_insights_view_denied_returns_404(client):
    with patch(
        "api.routers.sources.require_view_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.get("/api/sources/source:secret/insights")
    assert resp.status_code == 404


def test_retry_source_processing_mutate_denied_returns_403(client):
    with patch(
        "api.routers.sources.require_mutate_source",
        new=AsyncMock(side_effect=HTTPException(status_code=403, detail="You do not have permission to modify this source")),
    ):
        resp = client.post("/api/sources/source:x/retry")
    assert resp.status_code == 403


def test_retry_source_processing_not_viewable_returns_404(client):
    with patch(
        "api.routers.sources.require_mutate_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.post("/api/sources/source:x/retry")
    assert resp.status_code == 404


def test_create_source_insight_mutate_denied_returns_403(client):
    with patch(
        "api.routers.sources.require_mutate_source",
        new=AsyncMock(side_effect=HTTPException(status_code=403, detail="You do not have permission to modify this source")),
    ):
        resp = client.post(
            "/api/sources/source:x/insights",
            json={"transformation_id": "transformation:t1"},
        )
    assert resp.status_code == 403


def test_create_source_insight_not_viewable_returns_404(client):
    with patch(
        "api.routers.sources.require_mutate_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.post(
            "/api/sources/source:x/insights",
            json={"transformation_id": "transformation:t1"},
        )
    assert resp.status_code == 404


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
