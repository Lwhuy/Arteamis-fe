from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from open_notebook.exceptions import AuthenticationError


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
    monkeypatch.setenv("REFRESH_TOKEN_EXPIRE_DAYS", "30")


def test_identity_token_roundtrip():
    from api.security import create_identity_token, decode_identity_token

    token = create_identity_token("user:abc123")
    assert decode_identity_token(token) == "user:abc123"
    claims = jwt.decode(token, "unit-test-secret", algorithms=["HS256"])
    assert claims["type"] == "identity"
    assert claims["sub"] == "user:abc123"


def test_decode_identity_rejects_non_user_sub():
    from api.security import decode_identity_token

    bad = jwt.encode({"sub": "notauser", "type": "identity"}, "unit-test-secret", algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode_identity_token(bad)


def test_decode_identity_rejects_expired():
    from api.security import decode_identity_token

    expired = jwt.encode(
        {"sub": "user:x", "type": "identity", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        "unit-test-secret",
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError):
        decode_identity_token(expired)


def test_decode_identity_rejects_garbage():
    from api.security import decode_identity_token

    with pytest.raises(AuthenticationError):
        decode_identity_token("not-a-jwt")


def test_refresh_token_roundtrip_and_type_guard():
    from api.security import (
        create_identity_token,
        create_refresh_token,
        decode_refresh_token,
    )

    rt = create_refresh_token("user:abc")
    assert decode_refresh_token(rt) == "user:abc"
    # An identity token must NOT be accepted by the refresh decoder.
    it = create_identity_token("user:abc")
    with pytest.raises(AuthenticationError):
        decode_refresh_token(it)


def test_create_access_token_is_p2_stub():
    from api.security import create_access_token

    with pytest.raises(NotImplementedError):
        create_access_token("user:abc", "workspace:1", "owner")


def test_decode_access_token_returns_context_with_none_workspace_in_p1():
    from api.security import AuthContext, create_identity_token, decode_access_token

    ctx = decode_access_token(create_identity_token("user:abc"))
    assert isinstance(ctx, AuthContext)
    assert ctx.user_id == "user:abc"
    assert ctx.workspace_id is None
    assert ctx.role is None
