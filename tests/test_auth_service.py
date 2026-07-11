from types import SimpleNamespace
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


@pytest.mark.asyncio
async def test_login_unknown_email_runs_dummy_verify_for_timing():
    """Unknown-email path must pay the same argon2 cost as wrong-password,
    or response latency leaks whether an account exists (user enumeration)."""
    from api import auth_service

    dummy_verify = AsyncMock(return_value=False)
    with patch.object(User, "get_by_email", new=AsyncMock(return_value=None)), patch.object(
        User, "verify_password", new=dummy_verify
    ):
        with pytest.raises(AuthenticationError):
            await auth_service.login("nobody@b.com", "whatever")

    dummy_verify.assert_awaited_once_with("whatever")


@pytest.mark.asyncio
async def test_build_session_payload_shape():
    """P2: build_session_payload is now async and workspace-scoped — it
    auto-provisions the caller's personal workspace (see
    tests/test_p2_session_payload.py for the dedicated, thorough coverage of
    that behavior) and mints an access token for it instead of P1's bare
    identity token."""
    from api import auth_service
    from api.security import decode_access_token

    user = User(id="user:1", email="a@b.com", display_name="A")
    workspace = SimpleNamespace(id="workspace:p1", kind="personal")
    memberships = [
        {
            "workspace_id": "workspace:p1",
            "name": "Personal",
            "slug": "personal-1",
            "kind": "personal",
            "role": "owner",
            "created": "",
            "updated": "",
        }
    ]
    with patch.object(
        auth_service, "ensure_personal_workspace", new=AsyncMock(return_value=workspace)
    ), patch.object(
        auth_service, "list_memberships", new=AsyncMock(return_value=memberships)
    ):
        payload = await auth_service.build_session_payload(user)

    assert payload["token_type"] == "bearer"
    assert payload["needs_onboarding"] is True  # no company workspace yet
    assert payload["active_workspace_id"] == "workspace:p1"
    assert payload["memberships"] == memberships
    assert payload["user"] == {"id": "user:1", "email": "a@b.com", "display_name": "A"}
    ctx = decode_access_token(payload["access_token"])
    assert ctx.user_id == "user:1"
    assert ctx.workspace_id == "workspace:p1"
    assert ctx.role == "owner"
