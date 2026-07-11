from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.domain.invitation import Invitation


def _make(**over):
    base = dict(
        workspace="workspace:acme",
        email="alice@example.com",
        role="member",
        token_hash="deadbeef",
        invited_by="user:owner",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    base.update(over)
    return Invitation(**base)


def test_defaults_and_nullable_project():
    inv = _make()
    assert inv.status == "pending"
    assert inv.project is None
    # A workspace invite must persist project=None (nullable_fields lets it through).
    assert "project" in inv._prepare_save_data()
    assert inv._prepare_save_data()["project"] is None


def test_is_expired_true_and_false():
    assert _make(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)).is_expired() is True
    assert _make(expires_at=datetime.now(timezone.utc) + timedelta(days=1)).is_expired() is False
    # Naive datetimes coming back from SurrealDB are treated as UTC.
    naive_past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    assert _make(expires_at=naive_past).is_expired() is True


@pytest.mark.asyncio
async def test_get_by_token_hash_returns_none_when_absent():
    with patch(
        "open_notebook.domain.invitation.repo_query", new_callable=AsyncMock
    ) as q:
        q.return_value = []
        assert await Invitation.get_by_token_hash("nope") is None
        q.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_by_token_hash_hydrates_row():
    row = dict(
        id="invitation:1",
        workspace="workspace:acme",
        email="alice@example.com",
        role="member",
        project=None,
        token_hash="abc",
        status="pending",
        invited_by="user:owner",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    with patch(
        "open_notebook.domain.invitation.repo_query", new_callable=AsyncMock
    ) as q:
        q.return_value = [row]
        inv = await Invitation.get_by_token_hash("abc")
        assert inv is not None and inv.id == "invitation:1" and inv.status == "pending"
