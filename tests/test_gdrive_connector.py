from unittest.mock import AsyncMock, MagicMock

import pytest

from open_notebook.domain.connectors import gdrive as gdrive_mod
from open_notebook.domain.connectors.gdrive import GDriveConnector


class FakeAccessToken:
    def get_secret_value(self):
        return "tok-123"


class FakeConnection:
    access_token = FakeAccessToken()


def _resp(json_data):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json = MagicMock(return_value=json_data)
    return r


def test_authorize_url_has_offline_and_scopes(monkeypatch):
    monkeypatch.setenv("GDRIVE_CLIENT_ID", "cid")
    monkeypatch.setenv("GDRIVE_CLIENT_SECRET", "secret")
    url = GDriveConnector().authorize_url("STATE123", "http://localhost:5055/api/connectors/gdrive/callback")
    assert "accounts.google.com" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=STATE123" in url
    assert "drive.readonly" in url


def test_is_configured_reflects_env(monkeypatch):
    monkeypatch.delenv("GDRIVE_CLIENT_ID", raising=False)
    assert GDriveConnector().is_configured() is False
    monkeypatch.setenv("GDRIVE_CLIENT_ID", "cid")
    monkeypatch.setenv("GDRIVE_CLIENT_SECRET", "sec")
    assert GDriveConnector().is_configured() is True


def test_pick_export_mime_for_google_doc():
    c = GDriveConnector()
    assert c._export_mime("application/vnd.google-apps.document") == "text/markdown"
    assert c._export_mime("application/pdf") is None  # binary download, not export


@pytest.mark.asyncio
async def test_list_items_follows_next_page_token(monkeypatch):
    page1 = _resp({
        "nextPageToken": "TOKEN1",
        "files": [{"id": "f1", "name": "one.txt", "mimeType": "text/plain",
                    "modifiedTime": "2024-01-01T00:00:00Z"}],
    })
    page2 = _resp({
        "files": [{"id": "f2", "name": "two.txt", "mimeType": "text/plain",
                    "modifiedTime": "2024-01-02T00:00:00Z"}],
    })

    client = AsyncMock()
    client.get = AsyncMock(side_effect=[page1, page2])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(gdrive_mod.httpx, "AsyncClient", MagicMock(return_value=client))

    items = await GDriveConnector().list_items(FakeConnection())

    assert [i.id for i in items] == ["f1", "f2"]
    assert client.get.await_count == 2
    first_call_kwargs = client.get.await_args_list[0].kwargs
    second_call_kwargs = client.get.await_args_list[1].kwargs
    assert "pageToken" not in first_call_kwargs["params"]
    assert second_call_kwargs["params"]["pageToken"] == "TOKEN1"
