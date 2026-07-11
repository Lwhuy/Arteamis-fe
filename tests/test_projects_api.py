"""Workspace-scoped /projects router tests.

P6: this router is migrated onto ScopedRepository (api.deps.CtxDep) — the DB
calls it makes now go through open_notebook.database.scoping's repo_query/
repo_create/repo_update, not api.routers.projects' own module-level imports
(there are none left; ScopedRepository is the only sanctioned entry point).
Tests patch the scoping module accordingly. We still override P2's
get_auth_context with a synthetic AuthContext so the role gate and workspace
scoping run exactly as in production. A "personal" workspace token always
carries role="owner" (P2 invariant), so the same require_role("owner","admin")
gate serves both workspace kinds.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.deps import get_auth_context
from api.security import AuthContext


def _ctx(role="owner", workspace_id="workspace:a", user_id="user:1"):
    return AuthContext(user_id=user_id, workspace_id=workspace_id, role=role)


def _row(**over):
    base = dict(
        id="notebook:1",
        name="Acme",
        description="",
        archived=False,
        created="2026-01-01T00:00:00",
        updated="2026-01-01T00:00:00",
        source_count=2,
        note_count=1,
        workspace="workspace:a",
        owner="user:1",
        default_source_scope="project",
        promoted_from=None,
    )
    base.update(over)
    return base


@pytest.fixture
def client():
    from api.main import app

    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _override(app, ctx):
    app.dependency_overrides[get_auth_context] = lambda: ctx


class TestProjectList:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_list_scopes_by_workspace(self, mock_q, client):
        from api.main import app

        _override(app, _ctx(role="member"))
        mock_q.return_value = [_row()]
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

    @patch("open_notebook.database.scoping.repo_create", new_callable=AsyncMock)
    def test_admin_creates_and_seeds_admin_member(self, mock_create, client):
        from api.main import app

        _override(app, _ctx(role="admin"))

        async def _fake_create(table, data):
            if table == "notebook":
                return {
                    "id": "notebook:new",
                    "created": "t",
                    "updated": "t",
                    **data,
                }
            return {"id": "project_member:new", **data}

        mock_create.side_effect = _fake_create
        resp = client.post(
            "/api/projects",
            json={"name": "Acme", "default_source_scope": "project"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["id"] == "notebook:new"
        assert body["workspace"] == "workspace:a" and body["owner"] == "user:1"
        assert body["default_source_scope"] == "project"
        # a project_member(admin, active) row is seeded for the creator
        seed_table, seed_data = mock_create.await_args_list[-1].args
        assert seed_table == "project_member"
        assert seed_data["role"] == "admin" and seed_data["status"] == "active"

    @patch("open_notebook.database.scoping.repo_create", new_callable=AsyncMock)
    def test_personal_workspace_owner_creates_freely(self, mock_create, client):
        """A personal workspace has exactly one member, always role='owner' — the
        same require_role('owner','admin') gate that restricts company-workspace
        members also lets the personal owner create, with no separate code path.
        """
        from api.main import app

        _override(
            app,
            _ctx(role="owner", workspace_id="workspace:personal_default", user_id="user:1"),
        )

        async def _fake_create(table, data):
            if table == "notebook":
                return {"id": "notebook:personal1", "created": "t", "updated": "t", **data}
            return {"id": "project_member:new", **data}

        mock_create.side_effect = _fake_create
        resp = client.post("/api/projects", json={"name": "My personal project"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["workspace"] == "workspace:personal_default"
        assert body["default_source_scope"] == "personal"

    def test_empty_name_rejected(self, client):
        from api.main import app

        _override(app, _ctx(role="owner"))
        resp = client.post("/api/projects", json={"name": "   "})
        assert resp.status_code in (400, 422)


class TestProjectDetail:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_get_cross_workspace_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx(role="owner", workspace_id="workspace:a"))
        mock_q.return_value = []  # repo.get() ownership check finds nothing
        resp = client.get("/api/projects/notebook:1")
        assert resp.status_code == 404  # existence hidden across tenants

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_get_in_workspace_ok_and_stamps_view(self, mock_q, client):
        from api.main import app

        _override(app, _ctx(role="admin", workspace_id="workspace:a"))
        # 1) repo.get() ownership check, 2) counts raw query, 3) last_viewed stamp
        mock_q.side_effect = [
            [_row()],
            [_row(source_count=3, note_count=2)],
            [],
        ]
        resp = client.get("/api/projects/notebook:1")
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_count"] == 3
        assert "last_viewed_at = time::now()" in mock_q.await_args_list[2].args[0]

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_update_project_member_forbidden(self, mock_q, client):
        from api.main import app

        _override(app, _ctx(role="member", workspace_id="workspace:a", user_id="user:5"))
        # 1) repo.get() ownership check passes, 2) project_member admin lookup empty
        mock_q.side_effect = [[_row()], []]
        resp = client.put("/api/projects/notebook:1", json={"name": "New"})
        assert resp.status_code == 403

    @patch("open_notebook.database.scoping.repo_update", new_callable=AsyncMock)
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_update_workspace_admin_ok(self, mock_q, mock_update, client):
        from api.main import app

        _override(app, _ctx(role="admin", workspace_id="workspace:a"))
        # 1) repo.get() explicit ownership check, 2) repo.update()'s internal
        # get() ownership re-check, 3) repo.get() inside get_project,
        # 4) counts raw query (source of the response), 5) last_viewed stamp
        mock_q.side_effect = [
            [_row()],
            [_row()],
            [_row()],
            [_row(name="New")],
            [],
        ]
        mock_update.return_value = [{"id": "notebook:1"}]
        resp = client.put("/api/projects/notebook:1", json={"name": "New"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "New"

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.delete", new_callable=AsyncMock)
    def test_delete_workspace_owner_ok_and_clears_members(self, mock_del, mock_q, client):
        from api.main import app

        _override(app, _ctx(role="owner", workspace_id="workspace:a"))
        # 1) repo.get() ownership check, 2) project_member cleanup raw delete
        mock_q.side_effect = [[_row()], []]
        mock_del.return_value = {"deleted_notes": 1, "deleted_sources": 0, "unlinked_sources": 2}
        resp = client.delete("/api/projects/notebook:1")
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted_notes"] == 1
        assert any(
            "DELETE project_member" in c.args[0] for c in mock_q.await_args_list
        )

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    @patch("api.routers.projects.Project.get_delete_preview", new_callable=AsyncMock)
    def test_delete_preview_in_workspace(self, mock_prev, mock_q, client):
        from api.main import app

        _override(app, _ctx(role="owner", workspace_id="workspace:a"))
        mock_q.return_value = [_row()]  # repo.get() ownership check
        mock_prev.return_value = {"note_count": 2, "exclusive_source_count": 1, "shared_source_count": 0}
        resp = client.get("/api/projects/notebook:1/delete-preview")
        assert resp.status_code == 200, resp.text
        assert resp.json()["note_count"] == 2


class TestProjectSources:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_add_source_creates_reference(self, mock_q, client):
        """Workspace admin authorizes via repo.role short-circuit (no project_member
        query needed) -- exercises the success path of _authorize_project_write."""
        from api.main import app

        _override(app, _ctx(role="admin", workspace_id="workspace:a", user_id="user:5"))
        # 1) repo.get(project) ownership check, 2) _get_owned_source lookup,
        # 3) existing-ref check empty, 4) RELATE
        mock_q.side_effect = [[_row()], [{"id": "source:1"}], [], []]
        resp = client.post("/api/projects/notebook:1/sources/source:1")
        assert resp.status_code == 200, resp.text
        assert any("RELATE" in c.args[0] for c in mock_q.await_args_list)

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_remove_source_deletes_reference(self, mock_q, client):
        """Workspace owner authorizes via repo.role short-circuit."""
        from api.main import app

        _override(app, _ctx(role="owner", workspace_id="workspace:a", user_id="user:5"))
        mock_q.side_effect = [[_row()], []]
        resp = client.delete("/api/projects/notebook:1/sources/source:1")
        assert resp.status_code == 200, resp.text

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_add_source_plain_member_forbidden(self, mock_q, client):
        """A plain workspace member with no admin project_member row must be
        denied -- linking a source is a project-write action, same gate as
        update/delete."""
        from api.main import app

        _override(app, _ctx(role="member", workspace_id="workspace:a", user_id="user:5"))
        # 1) repo.get(project) ownership check, 2) project_member admin lookup empty
        mock_q.side_effect = [[_row()], []]
        resp = client.post("/api/projects/notebook:1/sources/source:1")
        assert resp.status_code == 403
        # Only 2 calls: never got to _get_owned_source
        assert mock_q.await_count == 2

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_remove_source_plain_member_forbidden(self, mock_q, client):
        from api.main import app

        _override(app, _ctx(role="member", workspace_id="workspace:a", user_id="user:5"))
        mock_q.side_effect = [[_row()], []]
        resp = client.delete("/api/projects/notebook:1/sources/source:1")
        assert resp.status_code == 403

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_add_source_project_admin_member_ok(self, mock_q, client):
        """A workspace member who IS an active admin project_member is
        authorized to link a source, via the project_member fallback branch."""
        from api.main import app

        _override(app, _ctx(role="member", workspace_id="workspace:a", user_id="user:5"))
        # 1) repo.get(project), 2) admin project_member lookup -> found,
        # 3) _get_owned_source lookup, 4) existing-ref check empty, 5) RELATE
        mock_q.side_effect = [
            [_row()],
            [{"id": "project_member:1"}],
            [{"id": "source:1"}],
            [],
            [],
        ]
        resp = client.post("/api/projects/notebook:1/sources/source:1")
        assert resp.status_code == 200, resp.text

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_add_source_not_owned_is_404(self, mock_q, client):
        """A source not referenced by any notebook in the caller's workspace
        cannot be 'adopted' into a project by guessing its id (P6 prep-design
        §3.10 fix)."""
        from api.main import app

        _override(app, _ctx(role="owner", workspace_id="workspace:a", user_id="user:5"))
        # 1) repo.get(project) ok, 2) _get_owned_source finds nothing
        mock_q.side_effect = [[_row()], []]
        resp = client.post("/api/projects/notebook:1/sources/source:999")
        assert resp.status_code == 404


class TestRecentlyViewed:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_recently_viewed_scopes_projects_by_workspace(self, mock_q, client):
        from api.main import app

        _override(app, _ctx(role="member", workspace_id="workspace:a"))
        mock_q.side_effect = [
            [{"id": "notebook:1", "title": "Acme", "last_viewed_at": "2026-06-27T10:00:00Z"}],
            [{"id": "source:1", "title": "Src", "last_viewed_at": "2026-06-27T09:00:00Z"}],
        ]
        resp = client.get("/api/recently-viewed")
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["type"] == "project" and body[0]["id"] == "notebook:1"
        assert "workspace = $workspace_id" in mock_q.await_args_list[0].args[0]
        # P6 prep-design §3.10 fix: the source half is now scoped too
        assert "workspace = $workspace_id" in mock_q.await_args_list[1].args[0]
