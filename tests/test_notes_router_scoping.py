"""Workspace-scoped /notes router tests (P6 rollout).

`note` has no native `workspace` column — it inherits workspace transitively
via the `artifact` edge to a notebook (open_notebook/database/scoping.py's
INHERITED_WORKSPACE_TABLES). Every read/mutate here goes through
ScopedRepository.raw() with an explicit parent-join filter, mirroring
`_get_owned_source` in api/routers/projects.py. No live DB needed: we override
api.deps.get_auth_context and patch open_notebook.database.scoping.repo_query
(ScopedRepository's own binding) plus open_notebook.domain.base's repo_*
bindings (Note.get/save/delete go through the domain layer directly).
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.deps import get_auth_context
from api.security import AuthContext


def _ctx(role="owner", workspace_id="workspace:a", user_id="user:1"):
    return AuthContext(user_id=user_id, workspace_id=workspace_id, role=role)


def _note_row(**over):
    base = dict(
        id="note:1",
        title="My note",
        content="hello",
        note_type="human",
        created="2026-01-01T00:00:00",
        updated="2026-01-01T00:00:00",
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


class TestNotesRequireWorkspace:
    def test_list_notes_401_without_token(self, client):
        resp = client.get("/api/notes")
        assert resp.status_code == 401


class TestNotesList:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_list_all_notes_scopes_via_artifact_edge(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = [_note_row()]
        resp = client.get("/api/notes")
        assert resp.status_code == 200, resp.text
        assert resp.json()[0]["id"] == "note:1"
        query = mock_q.await_args_list[0].args[0]
        assert "artifact" in query and "workspace_id" in query

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_list_notes_for_cross_workspace_notebook_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []  # repo.get(notebook_id) ownership check finds nothing
        resp = client.get("/api/notes", params={"notebook_id": "notebook:other"})
        assert resp.status_code == 404

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_list_notes_for_own_notebook_ok(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.side_effect = [
            [{"id": "notebook:1", "workspace": "workspace:a"}],  # repo.get() ownership check
            [_note_row()],  # notebook-filtered notes
        ]
        resp = client.get("/api/notes", params={"notebook_id": "notebook:1"})
        assert resp.status_code == 200, resp.text
        assert resp.json()[0]["id"] == "note:1"


class TestNotesGet:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_get_cross_workspace_note_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []  # ownership join finds nothing
        resp = client.get("/api/notes/note:1")
        assert resp.status_code == 404

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_get_own_note_ok(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = [_note_row()]
        resp = client.get("/api/notes/note:1")
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == "note:1"


class TestNotesCreate:
    def test_create_without_notebook_id_is_rejected(self, client):
        """A note with no notebook_id has no `artifact` edge to any notebook,
        and `note` has no native `workspace` column (INHERITED_WORKSPACE_TABLES
        in open_notebook/database/scoping.py) -- so an orphan note would be
        permanently unreachable via every workspace-scoped read, including by
        its own creator (fail-closed, not just fail-safe). The frontend never
        creates a note without a notebookId (NoteEditorDialog, MessageActions,
        SaveToNotebooksDialog all guard on it), so notebook_id is required at
        creation to make that orphan state unreachable rather than silently
        producing unrecoverable data."""
        from api.main import app

        _override(app, _ctx())
        resp = client.post("/api/notes", json={"content": "hi"})
        assert resp.status_code == 422, resp.text

    @patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
    @patch("open_notebook.domain.notebook.submit_command", return_value=None)
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_create_with_cross_workspace_notebook_is_404(
        self, mock_scoped_q, mock_submit, mock_create, client
    ):
        from api.main import app

        _override(app, _ctx())
        mock_scoped_q.return_value = []  # repo.get(notebook_id) ownership check finds nothing
        resp = client.post(
            "/api/notes",
            json={"content": "hi", "notebook_id": "notebook:other"},
        )
        assert resp.status_code == 404
        mock_create.assert_not_awaited()

    @patch("open_notebook.domain.notebook.Note.add_to_notebook", new_callable=AsyncMock)
    @patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
    @patch("open_notebook.domain.notebook.submit_command", return_value=None)
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_create_with_own_notebook_ok(
        self, mock_scoped_q, mock_submit, mock_create, mock_add, client
    ):
        from api.main import app

        _override(app, _ctx())
        mock_scoped_q.return_value = [{"id": "notebook:1", "workspace": "workspace:a"}]
        mock_create.return_value = _note_row()
        resp = client.post(
            "/api/notes",
            json={"content": "hi", "notebook_id": "notebook:1"},
        )
        assert resp.status_code == 200, resp.text
        mock_add.assert_awaited_once()


class TestNotesUpdateDelete:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_update_cross_workspace_note_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []  # ownership join finds nothing
        resp = client.put("/api/notes/note:1", json={"title": "hijacked"})
        assert resp.status_code == 404

    @patch("open_notebook.domain.notebook.Note.delete", new_callable=AsyncMock)
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_delete_own_note_ok(self, mock_q, mock_delete, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.side_effect = [
            [_note_row()],  # ownership join (in _get_owned_note)
            [_note_row()],  # Note.get() -> ObjectModel.get() uses repo_query too... see note below
        ]
        # Note.get() goes through open_notebook.domain.base.repo_query, not the
        # scoping module — patch that binding directly for the actual fetch.
        with patch(
            "open_notebook.domain.base.repo_query",
            new=AsyncMock(return_value=[_note_row()]),
        ):
            resp = client.delete("/api/notes/note:1")
        assert resp.status_code == 200, resp.text
        mock_delete.assert_awaited_once()

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_delete_cross_workspace_note_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []  # ownership join finds nothing
        resp = client.delete("/api/notes/note:1")
        assert resp.status_code == 404
