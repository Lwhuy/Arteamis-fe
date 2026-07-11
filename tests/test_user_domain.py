from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.domain.user import AuthIdentity, User
from open_notebook.exceptions import InvalidInputError


def test_normalize_email_lowercases_and_strips():
    assert User.normalize_email("  Foo@Bar.COM ") == "foo@bar.com"


def test_email_field_validator_lowercases():
    u = User(email="  Foo@Bar.com ")
    assert u.email == "foo@bar.com"


def test_email_rejects_empty():
    with pytest.raises((InvalidInputError, ValueError)):
        User(email="   ")


@pytest.mark.asyncio
async def test_set_and_verify_password_argon2():
    u = User(email="a@b.com")
    await u.set_password("hunter2-strong")
    assert u.password_hash is not None
    assert u.password_hash != "hunter2-strong"
    assert u.password_hash.startswith("$argon2")
    assert await u.verify_password("hunter2-strong") is True
    assert await u.verify_password("wrong-password") is False


@pytest.mark.asyncio
async def test_verify_password_false_when_no_hash():
    u = User(email="google@only.com")  # Google-only account, password_hash None
    assert u.password_hash is None
    assert await u.verify_password("anything") is False


@pytest.mark.asyncio
async def test_get_by_email_queries_lowercased():
    with patch("open_notebook.domain.user.repo_query", new=AsyncMock(return_value=[])) as q:
        result = await User.get_by_email("MixedCase@Example.com")
    assert result is None
    q.assert_awaited_once()
    _, kwargs_or_vars = q.await_args.args
    assert kwargs_or_vars == {"email": "mixedcase@example.com"}


@pytest.mark.asyncio
async def test_auth_identity_prepare_save_data_coerces_user_to_recordid():
    from surrealdb import RecordID

    ident = AuthIdentity(
        provider="google", provider_subject="sub-123", user="user:abc", email="a@b.com"
    )
    data = ident._prepare_save_data()
    assert isinstance(data["user"], RecordID)
    assert str(data["user"]) == "user:abc"


@pytest.mark.asyncio
async def test_upsert_with_identity_existing_identity_returns_user():
    existing = User(id="user:existing", email="a@b.com")
    with patch.object(User, "get_by_identity", new=AsyncMock(return_value=existing)) as gbi, patch(
        "open_notebook.domain.user.repo_query", new=AsyncMock(return_value=[])
    ) as q:
        result = await User.upsert_with_identity("google", "sub-1", "a@b.com", "A")
    assert result is existing
    gbi.assert_awaited_once_with("google", "sub-1")
    # An UPDATE to stamp last_login_at is issued; no new user/identity saved.
    q.assert_awaited()


@pytest.mark.asyncio
async def test_upsert_with_identity_new_user_creates_user_and_identity():
    saved_users = []
    saved_idents = []

    async def fake_user_save(self):
        self.id = "user:new"
        saved_users.append(self)

    async def fake_ident_save(self):
        self.id = "auth_identity:new"
        saved_idents.append(self)

    with patch.object(User, "get_by_identity", new=AsyncMock(return_value=None)), patch.object(
        User, "get_by_email", new=AsyncMock(return_value=None)
    ), patch.object(User, "save", new=fake_user_save), patch.object(
        AuthIdentity, "save", new=fake_ident_save
    ):
        result = await User.upsert_with_identity("google", "sub-9", "New@B.com", "New")

    assert result.id == "user:new"
    assert result.email == "new@b.com"
    assert len(saved_users) == 1
    assert len(saved_idents) == 1
    assert saved_idents[0].user == "user:new"
    assert saved_idents[0].provider == "google"
    assert saved_idents[0].provider_subject == "sub-9"
