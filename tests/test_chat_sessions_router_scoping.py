"""Workspace-scoped /chat/sessions + /chat/execute router tests (P6 rollout).

`chat_session` has no native `workspace` column — it inherits workspace
transitively via the `refers_to` edge to a notebook (INHERITED_WORKSPACE_TABLES
in open_notebook/database/scoping.py). Before this rollout, get/update/delete
/chat/sessions/{id} and POST /chat/execute took no workspace check at all: a
caller who could guess or observe a chat_session id from another workspace
could read its messages, rename/delete it, or inject a message into its
LangGraph checkpoint thread. These tests exercise the fix with no live DB:
override api.deps.get_auth_context and patch
open_notebook.database.scoping.repo_query (ScopedRepository's own binding).
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


class TestChatSessionsRequireWorkspace:
    def test_get_sessions_401_without_token(self, client):
        resp = client.get("/api/chat/sessions", params={"notebook_id": "notebook:1"})
        assert resp.status_code == 401


class TestGetSessions:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_cross_workspace_notebook_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []  # repo.get(notebook_id) ownership check finds nothing
        resp = client.get("/api/chat/sessions", params={"notebook_id": "notebook:other"})
        assert resp.status_code == 404

    @patch("api.routers.chat.get_session_message_count", new_callable=AsyncMock)
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_own_notebook_lists_sessions(self, mock_q, mock_count, client):
        from api.main import app

        _override(app, _ctx())
        mock_count.return_value = 3
        session_row = {
            "id": "chat_session:1", "title": "Chat", "created": "t", "updated": "t",
            "model_override": None,
        }
        mock_q.side_effect = [
            [{"id": "notebook:1", "workspace": "workspace:a"}],  # repo.get() ownership check
            [{"chat_session": [session_row]}],  # sessions-for-notebook raw query
        ]
        resp = client.get("/api/chat/sessions", params={"notebook_id": "notebook:1"})
        assert resp.status_code == 200, resp.text
        assert resp.json()[0]["id"] == "chat_session:1"


class TestCreateSession:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_cross_workspace_notebook_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []
        resp = client.post("/api/chat/sessions", json={"notebook_id": "notebook:other"})
        assert resp.status_code == 404

    @patch("open_notebook.domain.notebook.ChatSession.relate_to_notebook", new_callable=AsyncMock)
    @patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_own_notebook_creates_session(self, mock_scoped_q, mock_create, mock_relate, client):
        from api.main import app

        _override(app, _ctx())
        mock_scoped_q.return_value = [{"id": "notebook:1", "workspace": "workspace:a"}]
        mock_create.return_value = {
            "id": "chat_session:new", "title": "Chat Session 1", "created": "t", "updated": "t",
        }
        resp = client.post("/api/chat/sessions", json={"notebook_id": "notebook:1"})
        assert resp.status_code == 200, resp.text
        mock_relate.assert_awaited_once()


class TestSessionDetailMutation:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_get_session_cross_workspace_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []  # ownership join finds nothing
        resp = client.get("/api/chat/sessions/chat_session:1")
        assert resp.status_code == 404

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_update_session_cross_workspace_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []
        resp = client.put("/api/chat/sessions/chat_session:1", json={"title": "hijacked"})
        assert resp.status_code == 404

    @patch("open_notebook.domain.notebook.ChatSession.delete", new_callable=AsyncMock)
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_delete_session_cross_workspace_is_404(self, mock_q, mock_delete, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []
        resp = client.delete("/api/chat/sessions/chat_session:1")
        assert resp.status_code == 404
        mock_delete.assert_not_awaited()


class TestExecuteChat:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_execute_chat_on_cross_workspace_session_is_404(self, mock_q, client):
        """The real leak this rollout closes: previously any session_id was
        accepted with no ownership check at all, letting a caller inject a
        message into (and read the LangGraph history of) another workspace's
        chat session."""
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []  # ownership join finds nothing
        resp = client.post(
            "/api/chat/execute",
            json={"session_id": "chat_session:1", "message": "hi", "context": {}},
        )
        assert resp.status_code == 404
