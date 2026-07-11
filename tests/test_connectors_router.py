import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.source_permissions import PermissionContext, get_permission_context


@pytest.fixture
def ctx():
    return PermissionContext(
        user_id="user:1", workspace_id="workspace:1", workspace_role="owner"
    )


@pytest.fixture
def client(ctx):
    app.dependency_overrides[get_permission_context] = lambda: ctx
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_connectors_endpoint(monkeypatch, client):
    # Mocked DB-free: the real query (Connection.get_by_provider_and_workspace)
    # needs a live SurrealDB; here we only need to prove the endpoint is wired
    # to the ctx-scoped service call.
    async def fake_list_connectors_with_connections(workspace_id):
        assert workspace_id == "workspace:1"
        return [
            {"provider": "gdrive", "display_name": "Google Drive", "description": "d",
             "status": "available", "connections": []},
            {"provider": "slack", "display_name": "Slack", "description": "d",
             "status": "available", "connections": []},
            {"provider": "notion", "display_name": "Notion", "description": "d",
             "status": "available", "connections": []},
            {"provider": "s3", "display_name": "S3 Bucket", "description": "d",
             "status": "coming_soon", "connections": []},
        ]

    monkeypatch.setattr(
        "api.routers.connectors.svc.list_connectors_with_connections",
        fake_list_connectors_with_connections,
    )
    resp = client.get("/api/connectors")
    assert resp.status_code == 200
    providers = {c["provider"] for c in resp.json()}
    assert {"gdrive", "slack", "notion"}.issubset(providers)
    assert "s3" in providers


def test_callback_redirects_to_app(monkeypatch):
    # Callback is deliberately unauthenticated -- no ctx override, plain client.
    plain_client = TestClient(app)

    async def fake_handle(provider, code, state):
        class C:
            id = "connection:1"

        return C()
    monkeypatch.setattr("api.routers.connectors.svc.handle_callback", fake_handle)
    monkeypatch.setattr("api.routers.connectors.svc.app_redirect",
                        lambda q: f"http://localhost:3000/connections?{q}")
    resp = plain_client.get("/api/connectors/gdrive/callback?code=abc&state=xyz",
                            follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "connected=gdrive" in resp.headers["location"]


def test_callback_error_redirects_with_error(monkeypatch):
    plain_client = TestClient(app)

    async def boom(provider, code, state):
        raise ValueError("Invalid or expired OAuth state")
    monkeypatch.setattr("api.routers.connectors.svc.handle_callback", boom)
    monkeypatch.setattr("api.routers.connectors.svc.app_redirect",
                        lambda q: f"http://localhost:3000/connections?{q}")
    resp = plain_client.get("/api/connectors/gdrive/callback?code=abc&state=bad",
                            follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "error=" in resp.headers["location"]


def test_authorize_passes_ctx_to_service(monkeypatch, client, ctx):
    captured = {}

    def fake_build_authorize_url(provider, passed_ctx):
        captured["provider"] = provider
        captured["ctx"] = passed_ctx
        return "https://example.com/authorize"

    monkeypatch.setattr(
        "api.routers.connectors.svc.build_authorize_url", fake_build_authorize_url
    )
    resp = client.get("/api/connectors/gdrive/authorize")
    assert resp.status_code == 200
    assert captured["provider"] == "gdrive"
    assert captured["ctx"] is ctx


def test_import_items_passes_ctx_to_service(monkeypatch, client, ctx):
    captured = {}

    async def fake_import_items(provider, connection_id, item_ids, notebooks, passed_ctx):
        captured["ctx"] = passed_ctx
        return {"accepted": [], "failed": []}

    monkeypatch.setattr(
        "api.routers.connectors.svc.import_items", fake_import_items
    )
    resp = client.post(
        "/api/connectors/gdrive/import",
        json={"connection_id": "connection:1", "item_ids": ["a"]},
    )
    assert resp.status_code == 200
    assert captured["ctx"] is ctx


def test_import_items_cross_workspace_maps_to_400(monkeypatch, client):
    async def fake_import_items(provider, connection_id, item_ids, notebooks, ctx):
        raise ValueError("Connection does not belong to the active workspace")

    monkeypatch.setattr(
        "api.routers.connectors.svc.import_items", fake_import_items
    )
    resp = client.post(
        "/api/connectors/gdrive/import",
        json={"connection_id": "connection:1", "item_ids": ["a"]},
    )
    assert resp.status_code == 400


def test_list_items_passes_ctx_to_service(monkeypatch, client, ctx):
    captured = {}

    async def fake_list_items(provider, connection_id, passed_ctx):
        captured["ctx"] = passed_ctx
        return []

    monkeypatch.setattr("api.routers.connectors.svc.list_items", fake_list_items)
    resp = client.get("/api/connectors/gdrive/items?connection_id=connection:1")
    assert resp.status_code == 200
    assert captured["ctx"] is ctx


def test_disconnect_passes_ctx_to_service(monkeypatch, client, ctx):
    captured = {}

    async def fake_disconnect(connection_id, passed_ctx):
        captured["ctx"] = passed_ctx

    monkeypatch.setattr("api.routers.connectors.svc.disconnect", fake_disconnect)
    resp = client.delete("/api/connectors/connections/connection:1")
    assert resp.status_code == 204
    assert captured["ctx"] is ctx
