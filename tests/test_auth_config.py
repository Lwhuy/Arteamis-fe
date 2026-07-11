import pytest


def test_defaults_when_only_secret_set(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("JWT_ALGORITHM", raising=False)
    monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
    monkeypatch.delenv("REFRESH_COOKIE_NAME", raising=False)
    from api.auth_config import get_auth_config

    cfg = get_auth_config()
    assert cfg.jwt_secret == "test-secret"
    assert cfg.jwt_algorithm == "HS256"
    assert cfg.access_token_expire_minutes == 15
    assert cfg.refresh_token_expire_days == 30
    assert cfg.refresh_cookie_name == "arteamis_refresh"
    assert cfg.cookie_secure is True
    assert cfg.cookie_samesite == "lax"
    assert cfg.google_redirect_uri == "http://localhost:5055/api/auth/google/callback"
    assert cfg.frontend_url == "http://localhost:3000"


def test_auth_disabled_when_no_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET_FILE", raising=False)
    from api.auth_config import auth_enabled, get_auth_config

    assert get_auth_config().jwt_secret is None
    assert auth_enabled() is False


def test_cookie_secure_false_and_overrides(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "s")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "5")
    from api.auth_config import get_auth_config

    cfg = get_auth_config()
    assert cfg.cookie_secure is False
    assert cfg.access_token_expire_minutes == 5
