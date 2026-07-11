"""Workspace-scoped /projects router tests.

We override P2's get_auth_context with a synthetic AuthContext so the role gate
and workspace scoping run exactly as in production, and mock the repository
layer. A "personal" workspace token always carries role="owner" (P2 invariant),
so the same require_role("owner","admin") gate serves both workspace kinds.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.deps import get_auth_context
from api.security import AuthContext


def _ctx(role="owner", workspace_id="workspace:a", user_id="user:1"):
    return AuthContext(user_id=user_id, workspace_id=workspace_id, role=role)


@pytest.fixture
def client():
    from api.main import app

    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _override(app, ctx):
    app.dependency_overrides[get_auth_context] = lambda: ctx


class TestProjectList:
    @patch("api.routers.projects.repo_query", new_callable=AsyncMock)
    def test_list_scopes_by_workspace(self, mock_q, client):
        from api.main import app

        _override(app, _ctx(role="member"))
        mock_q.return_value = [
            {"id": "notebook:1", "name": "Acme", "description": "", "archived": False,
             "created": "t", "updated": "t", "source_count": 2, "note_count": 1,
             "workspace": "workspace:a", "owner": "user:1",
             "default_source_scope": "project", "promoted_from": None}
        ]
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["id"] == "notebook:1" and body[0]["workspace"] == "workspace:a"
        # workspace scoping is enforced in the query + params
        assert "WHERE workspace = $workspace_id" in mock_q.await_args_list[0].args[0]
        assert mock_q.await_args_list[0].args[1]["workspace_id"] is not None


class TestProjectCreate:
    def test_member_cannot_create_in_company_workspace(self, client):
        from api.main import app

        _override(app, _ctx(role="member"))
        resp = client.post("/api/projects", json={"name": "Acme"})
        assert resp.status_code == 403

    @patch("api.routers.projects.repo_query", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.save", new_callable=AsyncMock)
    def test_admin_creates_and_seeds_admin_member(self, mock_save, mock_q, client):
        from api.main import app

        _override(app, _ctx(role="admin"))

        async def _save(self):
            self.id = "notebook:new"
            self.created = "t"
            self.updated = "t"

        mock_save.side_effect = _save
        mock_q.return_value = []
        resp = client.post(
            "/api/projects",
            json={"name": "Acme", "default_source_scope": "project"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == "notebook:new"
        assert body["workspace"] == "workspace:a" and body["owner"] == "user:1"
        assert body["default_source_scope"] == "project"
        # a project_member(admin, active) row is seeded for the creator
        seed_sql = mock_q.await_args_list[-1].args[0]
        assert "project_member" in seed_sql and "'admin'" in seed_sql

    @patch("api.routers.projects.repo_query", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.save", new_callable=AsyncMock)
    def test_personal_workspace_owner_creates_freely(self, mock_save, mock_q, client):
        """A personal workspace has exactly one member, always role='owner' — the
        same require_role('owner','admin') gate that restricts company-workspace
        members also lets the personal owner create, with no separate code path.
        """
        from api.main import app

        _override(
            app,
            _ctx(role="owner", workspace_id="workspace:personal_default", user_id="user:1"),
        )

        async def _save(self):
            self.id = "notebook:personal1"
            self.created = "t"
            self.updated = "t"

        mock_save.side_effect = _save
        mock_q.return_value = []
        resp = client.post("/api/projects", json={"name": "My personal project"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["workspace"] == "workspace:personal_default"
        assert body["default_source_scope"] == "personal"

    def test_empty_name_rejected(self, client):
        from api.main import app

        _override(app, _ctx(role="owner"))
        resp = client.post("/api/projects", json={"name": "   "})
        assert resp.status_code in (400, 422)


class TestProjectDetail:
    @patch("api.routers.projects.repo_query", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.get", new_callable=AsyncMock)
    def test_get_cross_workspace_is_404(self, mock_get, mock_q, client):
        from api.main import app
        from open_notebook.domain.notebook import Project

        _override(app, _ctx(role="owner", workspace_id="workspace:a"))
        mock_get.return_value = Project(
            id="notebook:1", name="Acme", description="", workspace="workspace:b", owner="user:9"
        )
        resp = client.get("/api/projects/notebook:1")
        assert resp.status_code == 404  # existence hidden across tenants

    @patch("api.routers.projects.repo_query", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.get", new_callable=AsyncMock)
    def test_get_in_workspace_ok_and_stamps_view(self, mock_get, mock_q, client):
        from api.main import app
        from open_notebook.domain.notebook import Project

        _override(app, _ctx(role="admin", workspace_id="workspace:a"))
        mock_get.return_value = Project(
            id="notebook:1", name="Acme", description="", workspace="workspace:a", owner="user:1"
        )
        # first repo_query = counts, second = last_viewed stamp
        mock_q.side_effect = [
            [{"id": "notebook:1", "name": "Acme", "description": "", "archived": False,
              "created": "t", "updated": "t", "source_count": 3, "note_count": 2,
              "workspace": "workspace:a", "owner": "user:1",
              "default_source_scope": "project", "promoted_from": None}],
            [],
        ]
        resp = client.get("/api/projects/notebook:1")
        assert resp.status_code == 200
        assert resp.json()["source_count"] == 3
        assert "last_viewed_at = time::now()" in mock_q.await_args_list[1].args[0]

    @patch("api.routers.projects.repo_query", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.get", new_callable=AsyncMock)
    def test_update_project_member_forbidden(self, mock_get, mock_q, client):
        from api.main import app
        from open_notebook.domain.notebook import Project

        _override(app, _ctx(role="member", workspace_id="workspace:a", user_id="user:5"))
        mock_get.return_value = Project(
            id="notebook:1", name="Acme", description="", workspace="workspace:a", owner="user:1"
        )
        mock_q.return_value = []  # no admin project_member row for user:5
        resp = client.put("/api/projects/notebook:1", json={"name": "New"})
        assert resp.status_code == 403

    @patch("api.routers.projects.repo_query", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.save", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.get", new_callable=AsyncMock)
    def test_update_workspace_admin_ok(self, mock_get, mock_save, mock_q, client):
        from api.main import app
        from open_notebook.domain.notebook import Project

        _override(app, _ctx(role="admin", workspace_id="workspace:a"))
        mock_get.return_value = Project(
            id="notebook:1", name="Acme", description="", workspace="workspace:a", owner="user:1"
        )
        mock_q.return_value = [
            {"id": "notebook:1", "name": "New", "description": "", "archived": False,
             "created": "t", "updated": "t", "source_count": 0, "note_count": 0,
             "workspace": "workspace:a", "owner": "user:1",
             "default_source_scope": "personal", "promoted_from": None}
        ]
        resp = client.put("/api/projects/notebook:1", json={"name": "New"})
        assert resp.status_code == 200 and resp.json()["name"] == "New"

    @patch("api.routers.projects.repo_query", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.delete", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.get", new_callable=AsyncMock)
    def test_delete_workspace_owner_ok_and_clears_members(self, mock_get, mock_del, mock_q, client):
        from api.main import app
        from open_notebook.domain.notebook import Project

        _override(app, _ctx(role="owner", workspace_id="workspace:a"))
        mock_get.return_value = Project(
            id="notebook:1", name="Acme", description="", workspace="workspace:a", owner="user:1"
        )
        mock_del.return_value = {"deleted_notes": 1, "deleted_sources": 0, "unlinked_sources": 2}
        mock_q.return_value = []
        resp = client.delete("/api/projects/notebook:1")
        assert resp.status_code == 200 and resp.json()["deleted_notes"] == 1
        assert any(
            "DELETE project_member" in c.args[0] for c in mock_q.await_args_list
        )

    @patch("api.routers.projects.repo_query", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.get_delete_preview", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.get", new_callable=AsyncMock)
    def test_delete_preview_in_workspace(self, mock_get, mock_prev, mock_q, client):
        from api.main import app
        from open_notebook.domain.notebook import Project

        _override(app, _ctx(role="owner", workspace_id="workspace:a"))
        mock_get.return_value = Project(
            id="notebook:1", name="Acme", description="", workspace="workspace:a", owner="user:1"
        )
        mock_prev.return_value = {"note_count": 2, "exclusive_source_count": 1, "shared_source_count": 0}
        resp = client.get("/api/projects/notebook:1/delete-preview")
        assert resp.status_code == 200 and resp.json()["note_count"] == 2
