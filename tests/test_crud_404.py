"""Regression tests for #862: mutating/CRUD endpoints must return 404 (not 500)
for a non-existent resource.

`ObjectModel.get()` raises `NotFoundError` for a missing record (it never returns
a falsy value), so each handler needs an explicit `except NotFoundError -> 404`
arm before its broad `except Exception` (which would otherwise produce a 500).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from open_notebook.exceptions import NotFoundError


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def _nf(*_args, **_kwargs):
    raise NotFoundError("not found")


# --- projects (P3, replaces notebooks) --------------------------------------

from api.deps import get_auth_context  # noqa: E402
from api.security import AuthContext  # noqa: E402


def _member_ctx():
    return AuthContext(user_id="user:1", workspace_id="workspace:a", role="owner")


@pytest.mark.asyncio
@patch("api.routers.projects.Project.get", new_callable=AsyncMock)
async def test_delete_project_missing_returns_404(mock_get, client):
    from api.main import app

    app.dependency_overrides[get_auth_context] = _member_ctx
    mock_get.side_effect = _nf
    assert client.delete("/api/projects/notebook:gone").status_code == 404
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("api.routers.projects.Project.get", new_callable=AsyncMock)
async def test_update_project_missing_returns_404(mock_get, client):
    from api.main import app

    app.dependency_overrides[get_auth_context] = _member_ctx
    mock_get.side_effect = _nf
    assert client.put("/api/projects/notebook:gone", json={"name": "x"}).status_code == 404
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("api.routers.projects.Project.get", new_callable=AsyncMock)
async def test_delete_preview_missing_returns_404(mock_get, client):
    from api.main import app

    app.dependency_overrides[get_auth_context] = _member_ctx
    mock_get.side_effect = _nf
    assert client.get("/api/projects/notebook:gone/delete-preview").status_code == 404
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("api.routers.projects.Project.get", new_callable=AsyncMock)
async def test_add_source_missing_project_returns_404(mock_get, client):
    from api.main import app

    app.dependency_overrides[get_auth_context] = _member_ctx
    mock_get.side_effect = _nf
    assert client.post("/api/projects/notebook:gone/sources/source:1").status_code == 404
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("api.routers.projects.Project.get", new_callable=AsyncMock)
async def test_remove_source_missing_project_returns_404(mock_get, client):
    from api.main import app

    app.dependency_overrides[get_auth_context] = _member_ctx
    mock_get.side_effect = _nf
    assert client.delete("/api/projects/notebook:gone/sources/source:1").status_code == 404
    app.dependency_overrides.clear()


# --- notes ------------------------------------------------------------------


@pytest.mark.asyncio
@patch("api.routers.notes.Note.get", new_callable=AsyncMock)
async def test_get_note_missing_returns_404(mock_get, client):
    mock_get.side_effect = _nf
    assert client.get("/api/notes/note:gone").status_code == 404


@pytest.mark.asyncio
@patch("api.routers.notes.Note.get", new_callable=AsyncMock)
async def test_update_note_missing_returns_404(mock_get, client):
    mock_get.side_effect = _nf
    assert client.put("/api/notes/note:gone", json={"content": "x"}).status_code == 404


@pytest.mark.asyncio
@patch("api.routers.notes.Note.get", new_callable=AsyncMock)
async def test_delete_note_missing_returns_404(mock_get, client):
    mock_get.side_effect = _nf
    assert client.delete("/api/notes/note:gone").status_code == 404


# --- models -----------------------------------------------------------------


@pytest.mark.asyncio
@patch("api.routers.models.Model.get", new_callable=AsyncMock)
async def test_delete_model_missing_returns_404(mock_get, client):
    mock_get.side_effect = _nf
    assert client.delete("/api/models/model:gone").status_code == 404


# --- credentials ------------------------------------------------------------


@pytest.mark.asyncio
@patch("api.routers.credentials.require_encryption_key", new=MagicMock())
@patch("api.routers.credentials.Credential.get", new_callable=AsyncMock)
async def test_update_credential_missing_returns_404(mock_get, client):
    mock_get.side_effect = _nf
    assert client.put("/api/credentials/credential:gone", json={"name": "x"}).status_code == 404


@pytest.mark.asyncio
@patch("api.routers.credentials.Credential.get", new_callable=AsyncMock)
async def test_delete_credential_missing_returns_404(mock_get, client):
    mock_get.side_effect = _nf
    assert client.delete("/api/credentials/credential:gone").status_code == 404


# --- embedding --------------------------------------------------------------


@pytest.mark.asyncio
@patch("api.routers.embedding.Source.get", new_callable=AsyncMock)
@patch("api.routers.embedding.model_manager.get_embedding_model", new_callable=AsyncMock)
async def test_embed_missing_source_returns_404(mock_embed_model, mock_get, client):
    mock_embed_model.return_value = MagicMock()  # an embedding model is configured
    mock_get.side_effect = _nf
    resp = client.post(
        "/api/embed",
        json={"item_id": "source:gone", "item_type": "source", "async_processing": False},
    )
    assert resp.status_code == 404
