from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.source_permissions import PermissionContext, get_permission_context


@pytest.fixture
def client():
    from api.main import app

    ctx = PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role="member")
    app.dependency_overrides[get_permission_context] = lambda: ctx
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_session_view_denied_404(client):
    with patch(
        "api.routers.source_chat.require_view_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.post("/api/sources/source:secret/chat/sessions", json={"source_id": "source:secret"})
    assert resp.status_code == 404


def test_list_sessions_view_denied_404(client):
    with patch(
        "api.routers.source_chat.require_view_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.get("/api/sources/source:secret/chat/sessions")
    assert resp.status_code == 404


# ── P6 rollout: cross-workspace session/source combos --------------------
# `chat_session` here has no workspace check of its own, by design (see the
# module-level comment in api/routers/source_chat.py): require_view_source
# already 404s a source_id from another workspace, and every session lookup
# afterward is gated by an exact-match compound join (session_id AND
# out=<that same verified source_id>). A session that exists but belongs to
# a DIFFERENT source (e.g. one from another workspace) must therefore 404
# too -- these tests prove that fails safely rather than falling through to
# some other source's session.


def _mock_chat_session():
    from open_notebook.domain.notebook import ChatSession

    return ChatSession(
        id="chat_session:other", title="Someone else's session", model_override=None
    )


def test_get_session_belonging_to_different_source_is_404(client):
    with patch("api.routers.source_chat.require_view_source", new=AsyncMock(return_value=None)):
        with patch(
            "api.routers.source_chat.ChatSession.get",
            new=AsyncMock(return_value=_mock_chat_session()),
        ):
            with patch(
                "api.routers.source_chat.repo_query",
                new=AsyncMock(return_value=[]),  # relation_query: no match for this source_id
            ):
                resp = client.get(
                    "/api/sources/source:mine/chat/sessions/chat_session:other"
                )
    assert resp.status_code == 404


def test_update_session_belonging_to_different_source_is_404(client):
    with patch("api.routers.source_chat.require_view_source", new=AsyncMock(return_value=None)):
        with patch(
            "api.routers.source_chat.ChatSession.get",
            new=AsyncMock(return_value=_mock_chat_session()),
        ):
            with patch(
                "api.routers.source_chat.repo_query",
                new=AsyncMock(return_value=[]),
            ):
                resp = client.put(
                    "/api/sources/source:mine/chat/sessions/chat_session:other",
                    json={"title": "hijacked"},
                )
    assert resp.status_code == 404


def test_delete_session_belonging_to_different_source_is_404(client):
    with patch("api.routers.source_chat.require_view_source", new=AsyncMock(return_value=None)):
        with patch(
            "api.routers.source_chat.ChatSession.get",
            new=AsyncMock(return_value=_mock_chat_session()),
        ):
            with patch(
                "api.routers.source_chat.repo_query",
                new=AsyncMock(return_value=[]),
            ):
                resp = client.delete(
                    "/api/sources/source:mine/chat/sessions/chat_session:other"
                )
    assert resp.status_code == 404


def test_send_message_to_session_belonging_to_different_source_is_404(client):
    with patch("api.routers.source_chat.require_view_source", new=AsyncMock(return_value=None)):
        with patch(
            "api.routers.source_chat.ChatSession.get",
            new=AsyncMock(return_value=_mock_chat_session()),
        ):
            with patch(
                "api.routers.source_chat.repo_query",
                new=AsyncMock(return_value=[]),
            ):
                resp = client.post(
                    "/api/sources/source:mine/chat/sessions/chat_session:other/messages",
                    json={"message": "hi"},
                )
    assert resp.status_code == 404
