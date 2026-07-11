import importlib

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.auth import JWTAuthMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(JWTAuthMiddleware, excluded_paths=["/public"])

    @app.get("/public")
    async def public():
        return {"ok": True}

    @app.get("/private")
    async def private(request: Request):
        return {"user_id": getattr(request.state, "user_id", None)}

    return app


def test_open_passthrough_when_no_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET_FILE", raising=False)
    client = TestClient(_build_app())
    assert client.get("/private").status_code == 200


def test_missing_token_is_401(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "mw-secret")
    client = TestClient(_build_app())
    resp = client.get("/private")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Missing authorization header"}
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_valid_identity_token_sets_user_id(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "mw-secret")
    from api.security import create_identity_token

    token = create_identity_token("user:abc")
    client = TestClient(_build_app())
    resp = client.get("/private", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "user:abc"}


def test_invalid_token_is_401(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "mw-secret")
    client = TestClient(_build_app())
    resp = client.get("/private", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


def test_excluded_path_skips_auth(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "mw-secret")
    client = TestClient(_build_app())
    assert client.get("/public").status_code == 200


def test_password_middleware_is_gone():
    import api.auth as auth_mod

    importlib.reload(auth_mod)
    assert not hasattr(auth_mod, "PasswordAuthMiddleware")
