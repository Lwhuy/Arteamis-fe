"""Tests for recently viewed projects and sources (P3 /projects router)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.deps import get_auth_context
from api.security import AuthContext
from api.source_permissions import PermissionContext, get_permission_context
from open_notebook.domain.notebook import Source


def _ctx():
    return AuthContext(user_id="user:1", workspace_id="workspace:a", role="member")


def _perm_ctx():
    return PermissionContext(
        user_id="user:1", workspace_id="workspace:a", workspace_role="member"
    )


@pytest.fixture
def client():
    from api.main import app

    app.dependency_overrides[get_auth_context] = _ctx
    app.dependency_overrides[get_permission_context] = _perm_ctx
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


class TestRecentlyViewedApi:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_recently_viewed_returns_mixed_items_newest_first(self, mock_repo_query, client):
        mock_repo_query.side_effect = [
            [{"id": "notebook:old", "title": "Older Project", "last_viewed_at": "2026-06-26T10:00:00Z"}],
            [{"id": "source:new", "title": "Newer Source", "last_viewed_at": "2026-06-27T10:00:00Z"}],
        ]
        response = client.get("/api/recently-viewed")
        assert response.status_code == 200
        assert response.json() == [
            {"type": "source", "id": "source:new", "title": "Newer Source", "last_viewed_at": "2026-06-27T10:00:00Z"},
            {"type": "project", "id": "notebook:old", "title": "Older Project", "last_viewed_at": "2026-06-26T10:00:00Z"},
        ]

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_recently_viewed_honors_limit(self, mock_repo_query, client):
        mock_repo_query.side_effect = [
            [
                {"id": "notebook:1", "title": "Project 1", "last_viewed_at": "2026-06-27T09:00:00Z"},
                {"id": "notebook:2", "title": "Project 2", "last_viewed_at": "2026-06-27T07:00:00Z"},
            ],
            [
                {"id": "source:1", "title": "Source 1", "last_viewed_at": "2026-06-27T10:00:00Z"},
                {"id": "source:2", "title": "Source 2", "last_viewed_at": "2026-06-27T08:00:00Z"},
            ],
        ]
        response = client.get("/api/recently-viewed?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert [item["id"] for item in data] == ["source:1", "notebook:1"]
        assert len(data) == 2
        # both queries are passed workspace_id (repo.raw() always injects it) and limit
        assert mock_repo_query.await_args_list[0].args[1]["limit"] == 2
        assert mock_repo_query.await_args_list[1].args[1]["limit"] == 2
        assert "workspace_id" in mock_repo_query.await_args_list[1].args[1]

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_recently_viewed_empty_when_no_view_history(self, mock_repo_query, client):
        mock_repo_query.side_effect = [[], []]
        response = client.get("/api/recently-viewed")
        assert response.status_code == 200
        assert response.json() == []

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_get_project_stamps_last_viewed_at(self, mock_repo_query, client):
        row = {
            "id": "notebook:1", "name": "Project", "description": "", "archived": False,
            "created": "2026-06-27T09:00:00Z", "updated": "2026-06-27T09:00:00Z",
            "source_count": 0, "note_count": 0, "workspace": "workspace:a",
            "owner": "user:1", "default_source_scope": "personal", "promoted_from": None,
        }
        # 1) repo.get() ownership check, 2) counts raw query, 3) last_viewed stamp
        mock_repo_query.side_effect = [[row], [row], []]
        response = client.get("/api/projects/notebook:1")
        assert response.status_code == 200
        assert "last_viewed_at = time::now()" in mock_repo_query.await_args_list[2].args[0]

    @patch("api.routers.sources.Source.get_embedded_chunks", new_callable=AsyncMock)
    @patch("api.routers.sources.require_view_source", new_callable=AsyncMock)
    @patch("api.routers.sources.repo_query", new_callable=AsyncMock)
    def test_get_source_stamps_last_viewed_at(self, mock_repo_query, mock_get_source, mock_chunks, client):
        mock_get_source.return_value = Source(
            id="source:1", title="Source", topics=[], full_text="Source text",
            created="2026-06-27T09:00:00Z", updated="2026-06-27T09:00:00Z",
        )
        mock_chunks.return_value = 0
        mock_repo_query.side_effect = [[], []]
        response = client.get("/api/sources/source:1")
        assert response.status_code == 200
        assert "UPDATE $source_id SET last_viewed_at = time::now()" in mock_repo_query.await_args_list[0].args[0]
