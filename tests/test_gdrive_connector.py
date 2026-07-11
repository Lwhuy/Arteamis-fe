import pytest

from open_notebook.domain.connectors.gdrive import GDriveConnector


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
