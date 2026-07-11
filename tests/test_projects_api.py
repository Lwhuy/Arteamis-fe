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
