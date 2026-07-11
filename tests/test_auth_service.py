from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.domain.user import User
from open_notebook.exceptions import AuthenticationError, DuplicateResourceError


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "svc-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email():
    from api import auth_service

    with patch.object(User, "get_by_email", new=AsyncMock(return_value=User(id="user:1", email="a@b.com"))):
        with pytest.raises(DuplicateResourceError):
            await auth_service.register("a@b.com", "password123", "A")


@pytest.mark.asyncio
async def test_register_creates_user_and_identity():
    from api import auth_service

    saved_idents = []

    async def fake_user_save(self):
        self.id = "user:new"

    async def fake_ident_save(self):
        self.id = "auth_identity:new"
        saved_idents.append(self)

    from open_notebook.domain.user import AuthIdentity

    with patch.object(User, "get_by_email", new=AsyncMock(return_value=None)), patch.object(
        User, "save", new=fake_user_save
    ), patch.object(AuthIdentity, "save", new=fake_ident_save):
        user = await auth_service.register("New@B.com", "password123", "New")

    assert user.id == "user:new"
    assert user.email == "new@b.com"
    assert user.password_hash is not None and user.password_hash.startswith("$argon2")
    assert len(saved_idents) == 1
    assert saved_idents[0].provider == "email_password"
    assert saved_idents[0].provider_subject == "new@b.com"


@pytest.mark.asyncio
async def test_login_success_returns_user():
    from api import auth_service

    user = User(id="user:1", email="a@b.com")
    await user.set_password("correct-horse")
    with patch.object(User, "get_by_email", new=AsyncMock(return_value=user)):
        result = await auth_service.login("a@b.com", "correct-horse")
    assert result is user


@pytest.mark.asyncio
async def test_login_wrong_password_raises_generic():
    from api import auth_service

    user = User(id="user:1", email="a@b.com")
    await user.set_password("correct-horse")
    with patch.object(User, "get_by_email", new=AsyncMock(return_value=user)):
        with pytest.raises(AuthenticationError):
            await auth_service.login("a@b.com", "wrong")


@pytest.mark.asyncio
async def test_login_unknown_email_raises_same_error():
    from api import auth_service

    with patch.object(User, "get_by_email", new=AsyncMock(return_value=None)):
        with pytest.raises(AuthenticationError):
            await auth_service.login("nobody@b.com", "whatever")


def test_build_session_payload_shape():
    from api import auth_service
    from api.security import decode_identity_token

    user = User(id="user:1", email="a@b.com", display_name="A")
    payload = auth_service.build_session_payload(user)
    assert payload["token_type"] == "bearer"
    assert payload["needs_onboarding"] is True
    assert payload["active_workspace_id"] is None
    assert payload["memberships"] == []
    assert payload["user"] == {"id": "user:1", "email": "a@b.com", "display_name": "A"}
    assert decode_identity_token(payload["access_token"]) == "user:1"
