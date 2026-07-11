import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_list_connectors_endpoint(monkeypatch):
    resp = client.get("/api/connectors")
    assert resp.status_code == 200
    providers = {c["provider"] for c in resp.json()}
    assert {"gdrive", "slack", "notion"}.issubset(providers)
    assert "s3" in providers


def test_callback_redirects_to_app(monkeypatch):
    async def fake_handle(provider, code, state):
        class C:
            id = "connection:1"

        return C()
    monkeypatch.setattr("api.routers.connectors.svc.handle_callback", fake_handle)
    monkeypatch.setattr("api.routers.connectors.svc.app_redirect",
                        lambda q: f"http://localhost:3000/connections?{q}")
    resp = client.get("/api/connectors/gdrive/callback?code=abc&state=xyz",
                      follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "connected=gdrive" in resp.headers["location"]


def test_callback_error_redirects_with_error(monkeypatch):
    async def boom(provider, code, state):
        raise ValueError("Invalid or expired OAuth state")
    monkeypatch.setattr("api.routers.connectors.svc.handle_callback", boom)
    monkeypatch.setattr("api.routers.connectors.svc.app_redirect",
                        lambda q: f"http://localhost:3000/connections?{q}")
    resp = client.get("/api/connectors/gdrive/callback?code=abc&state=bad",
                      follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "error=" in resp.headers["location"]
