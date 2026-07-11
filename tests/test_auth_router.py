from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


async def _fake_build_session_payload(user):
    """P2: build_session_payload now auto-provisions a real workspace via the
    DB (ensure_personal_workspace/list_memberships), which these router tests
    must not hit — they only exercise routing/cookie behavior, and the
    workspace-provisioning behavior itself is covered by
    tests/test_p2_session_payload.py. Stand in with a minimal, workspace-scoped
    shape."""
    return {
        "access_token": "fake-access-token",
        "token_type": "bearer",
        "needs_onboarding": True,
        "active_workspace_id": "workspace:p1",
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name},
        "memberships": [],
    }


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    # JWT_SECRET set so real tokens are minted; but /auth/* are excluded paths
    # so the middleware never blocks these calls.
    monkeypatch.setenv("JWT_SECRET", "router-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("COOKIE_SECURE", "false")


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def test_register_success_sets_cookie_and_returns_session(client):
    from open_notebook.domain.user import User

    async def fake_register(email, password, display_name):
        u = User(id="user:new", email=email, display_name=display_name)
        return u

    with patch("api.routers.auth.auth_service.register", new=fake_register), patch(
        "api.routers.auth.auth_service.build_session_payload",
        new=_fake_build_session_payload,
    ):
        resp = client.post(
            "/api/auth/register",
            json={"email": "New@b.com", "password": "password123", "display_name": "New"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["needs_onboarding"] is True
    assert body["user"]["id"] == "user:new"
    assert "arteamis_refresh" in resp.cookies


def test_register_duplicate_email_is_409(client):
    from open_notebook.exceptions import DuplicateResourceError

    async def fake_register(email, password, display_name):
        raise DuplicateResourceError("Email already registered")

    with patch("api.routers.auth.auth_service.register", new=fake_register):
        resp = client.post(
            "/api/auth/register",
            json={"email": "dupe@b.com", "password": "password123"},
        )
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Email already registered"}


def test_register_short_password_is_422(client):
    resp = client.post(
        "/api/auth/register", json={"email": "a@b.com", "password": "short"}
    )
    assert resp.status_code == 422


def test_login_success(client):
    from open_notebook.domain.user import User

    async def fake_login(email, password):
        return User(id="user:1", email=email, display_name="A")

    with patch("api.routers.auth.auth_service.login", new=fake_login), patch(
        "api.routers.auth.auth_service.build_session_payload",
        new=_fake_build_session_payload,
    ):
        resp = client.post(
            "/api/auth/login", json={"email": "a@b.com", "password": "password123"}
        )
    assert resp.status_code == 200
    assert resp.json()["user"]["id"] == "user:1"


def test_login_bad_credentials_is_401(client):
    from open_notebook.exceptions import AuthenticationError

    async def fake_login(email, password):
        raise AuthenticationError("Invalid email or password")

    with patch("api.routers.auth.auth_service.login", new=fake_login):
        resp = client.post(
            "/api/auth/login", json={"email": "a@b.com", "password": "wrongpass1"}
        )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid email or password"}


def test_google_start_redirects_and_sets_state_cookie(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    resp = client.get("/api/auth/google/start", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "accounts.google.com" in resp.headers["location"]
    assert "arteamis_oauth_state" in resp.cookies


def test_google_callback_bad_state_is_400(client):
    resp = client.get(
        "/api/auth/google/callback?code=abc&state=mismatch", follow_redirects=False
    )
    assert resp.status_code == 400


def test_google_callback_unverified_email_is_400(client):
    async def fake_exchange(code):
        return {"sub": "g-1", "email": "u@gmail.com", "email_verified": False, "name": "U"}

    client.cookies.set("arteamis_oauth_state", "state123")
    with patch("api.routers.auth.google.exchange_code_for_userinfo", new=fake_exchange):
        resp = client.get(
            "/api/auth/google/callback?code=abc&state=state123", follow_redirects=False
        )
    assert resp.status_code == 400


def test_google_callback_success_redirects_frontend(client, monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    from open_notebook.domain.user import User

    async def fake_exchange(code):
        return {"sub": "g-1", "email": "u@gmail.com", "email_verified": True, "name": "U"}

    async def fake_upsert(provider, subject, email, display_name=None):
        return User(id="user:g", email=email, display_name=display_name)

    client.cookies.set("arteamis_oauth_state", "state123")
    with patch("api.routers.auth.google.exchange_code_for_userinfo", new=fake_exchange), patch(
        "api.routers.auth.User.upsert_with_identity", new=fake_upsert
    ):
        resp = client.get(
            "/api/auth/google/callback?code=abc&state=state123", follow_redirects=False
        )
    assert resp.status_code in (302, 307)
    assert resp.headers["location"].startswith("http://localhost:3000")
    assert "arteamis_refresh" in resp.cookies


def test_refresh_missing_cookie_is_401(client):
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401


def test_refresh_valid_cookie_returns_new_session(client):
    from api.security import create_refresh_token
    from open_notebook.domain.user import User

    with patch(
        "api.routers.auth.User.get", new=AsyncMock(return_value=User(id="user:1", email="a@b.com"))
    ), patch(
        "api.routers.auth.auth_service.build_session_payload",
        new=_fake_build_session_payload,
    ):
        client.cookies.set("arteamis_refresh", create_refresh_token("user:1"))
        resp = client.post("/api/auth/refresh")
    assert resp.status_code == 200
    assert resp.json()["user"]["id"] == "user:1"


def test_logout_clears_cookie(client):
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"status": "logged_out"}


def test_me_returns_user(client):
    from api.security import create_identity_token
    from open_notebook.domain.user import User

    token = create_identity_token("user:1")
    with patch("api.routers.auth.User.get", new=AsyncMock(return_value=User(id="user:1", email="a@b.com", display_name="A"))):
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user"] == {"id": "user:1", "email": "a@b.com", "display_name": "A"}
    assert resp.json()["memberships"] == []


def test_status_reports_enabled(client):
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    assert resp.json()["auth_enabled"] is True
