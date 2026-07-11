import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api import invitation_service as svc
from open_notebook.domain.invitation import Invitation


def _inv(**over):
    base = dict(
        id="invitation:1",
        workspace="workspace:acme",
        email="alice@example.com",
        role="member",
        project=None,
        token_hash=svc.hash_token("raw-token"),
        status="pending",
        invited_by="user:owner",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    base.update(over)
    return Invitation(**base)


def _workspace(kind="company", id="workspace:acme"):
    return SimpleNamespace(id=id, kind=kind, name="Acme")


def test_generate_token_returns_raw_and_matching_sha256():
    raw, token_hash = svc.generate_token()
    assert raw and token_hash != raw
    assert token_hash == hashlib.sha256(raw.encode()).hexdigest()


def test_build_invite_url_uses_env(monkeypatch):
    monkeypatch.setenv("OPEN_NOTEBOOK_APP_URL", "https://app.test")
    assert svc.build_invite_url("abc") == "https://app.test/invite/abc"
    monkeypatch.delenv("OPEN_NOTEBOOK_APP_URL", raising=False)
    assert svc.build_invite_url("abc") == "http://localhost:3000/invite/abc"


@pytest.mark.asyncio
async def test_create_invite_into_personal_workspace_403(monkeypatch):
    """NEW v2 guard: a kind=personal workspace can never be invited into."""
    monkeypatch.setattr(
        svc, "_get_workspace", AsyncMock(return_value=_workspace(kind="personal", id="workspace:p1"))
    )
    existing_pending = AsyncMock()
    monkeypatch.setattr(svc, "_existing_pending", existing_pending)
    with pytest.raises(HTTPException) as ei:
        await svc.create_invitation("workspace:p1", "user:owner", "a@x.com", "member", None)
    assert ei.value.status_code == 403
    existing_pending.assert_not_called()  # short-circuits before any other work


@pytest.mark.asyncio
async def test_create_workspace_invite_persists_pending_with_hash(monkeypatch):
    monkeypatch.setattr(svc, "_get_workspace", AsyncMock(return_value=_workspace()))
    monkeypatch.setattr(svc, "_existing_pending", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_email_has_active_membership", AsyncMock(return_value=False))
    saved = {}

    async def fake_save(self):
        self.id = "invitation:new"
        saved["inv"] = self

    with patch.object(Invitation, "save", fake_save):
        inv, raw = await svc.create_invitation(
            "workspace:acme", "user:owner", "Alice@Example.com", "member", None
        )
    assert inv.status == "pending"
    assert inv.email == "alice@example.com"  # normalized lower-case
    assert inv.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert inv.token_hash != raw
    assert inv.project is None
    assert (inv.expires_at - datetime.now(timezone.utc)).days in (6, 7)


@pytest.mark.asyncio
async def test_create_workspace_invite_conflict_when_already_active_member(monkeypatch):
    monkeypatch.setattr(svc, "_get_workspace", AsyncMock(return_value=_workspace()))
    monkeypatch.setattr(svc, "_existing_pending", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_email_has_active_membership", AsyncMock(return_value=True))
    with pytest.raises(HTTPException) as ei:
        await svc.create_invitation("workspace:acme", "user:owner", "a@x.com", "member", None)
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_create_rotates_existing_pending_invite(monkeypatch):
    monkeypatch.setattr(svc, "_get_workspace", AsyncMock(return_value=_workspace()))
    existing = _inv(token_hash="OLDHASH")
    monkeypatch.setattr(svc, "_existing_pending", AsyncMock(return_value=existing))
    monkeypatch.setattr(svc, "_email_has_active_membership", AsyncMock(return_value=False))
    with patch.object(Invitation, "save", AsyncMock()):
        inv, raw = await svc.create_invitation(
            "workspace:acme", "user:owner", "alice@example.com", "member", None
        )
    assert inv.id == "invitation:1"  # rotated the same row
    assert inv.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert inv.token_hash != "OLDHASH"


@pytest.mark.asyncio
async def test_accept_unknown_token_404(monkeypatch):
    monkeypatch.setattr(Invitation, "get_by_token_hash", AsyncMock(return_value=None))
    from open_notebook.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await svc.accept_invitation("raw-token", "user:alice")


@pytest.mark.asyncio
async def test_accept_non_pending_410(monkeypatch):
    monkeypatch.setattr(
        Invitation, "get_by_token_hash", AsyncMock(return_value=_inv(status="revoked"))
    )
    with pytest.raises(HTTPException) as ei:
        await svc.accept_invitation("raw-token", "user:alice")
    assert ei.value.status_code == 410


@pytest.mark.asyncio
async def test_accept_expired_flips_status_and_410(monkeypatch):
    inv = _inv(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    monkeypatch.setattr(Invitation, "get_by_token_hash", AsyncMock(return_value=inv))
    save = AsyncMock()
    monkeypatch.setattr(Invitation, "save", save)
    with pytest.raises(HTTPException) as ei:
        await svc.accept_invitation("raw-token", "user:alice")
    assert ei.value.status_code == 410
    assert inv.status == "expired"
    save.assert_awaited()  # lazily persisted the flip


@pytest.mark.asyncio
async def test_accept_email_mismatch_403(monkeypatch):
    inv = _inv(email="alice@example.com")
    monkeypatch.setattr(Invitation, "get_by_token_hash", AsyncMock(return_value=inv))

    class _U:
        email = "bob@example.com"

    from open_notebook.domain import user as user_mod

    monkeypatch.setattr(user_mod.User, "get", AsyncMock(return_value=_U()))
    with pytest.raises(HTTPException) as ei:
        await svc.accept_invitation("raw-token", "user:bob")
    assert ei.value.status_code == 403
    assert inv.status == "pending"  # unchanged


@pytest.mark.asyncio
async def test_accept_workspace_invite_activates_membership(monkeypatch):
    inv = _inv(email="alice@example.com", role="admin")
    monkeypatch.setattr(Invitation, "get_by_token_hash", AsyncMock(return_value=inv))

    class _U:
        email = "alice@example.com"

    from open_notebook.domain import user as user_mod

    monkeypatch.setattr(user_mod.User, "get", AsyncMock(return_value=_U()))
    upsert_m = AsyncMock()
    monkeypatch.setattr(svc, "_upsert_workspace_membership", upsert_m)
    monkeypatch.setattr(Invitation, "save", AsyncMock())

    result = await svc.accept_invitation("raw-token", "user:alice")
    upsert_m.assert_awaited_once_with("user:alice", "workspace:acme", "admin")
    assert result == {
        "workspace_id": "workspace:acme",
        "role": "admin",
        "project_id": None,
        "membership_status": "active",
    }
    assert inv.status == "accepted"


@pytest.mark.asyncio
async def test_accept_project_invite_activates_workspace_and_project_member(monkeypatch):
    inv = _inv(email="alice@example.com", role="admin", project="notebook:proj")
    monkeypatch.setattr(Invitation, "get_by_token_hash", AsyncMock(return_value=inv))

    class _U:
        email = "alice@example.com"

    from open_notebook.domain import user as user_mod

    monkeypatch.setattr(user_mod.User, "get", AsyncMock(return_value=_U()))
    upsert_m = AsyncMock()
    upsert_p = AsyncMock()
    monkeypatch.setattr(svc, "_upsert_workspace_membership", upsert_m)
    monkeypatch.setattr(svc, "_upsert_project_member", upsert_p)
    monkeypatch.setattr(Invitation, "save", AsyncMock())

    result = await svc.accept_invitation("raw-token", "user:alice")
    upsert_m.assert_awaited_once_with("user:alice", "workspace:acme", "member")  # shell access
    upsert_p.assert_awaited_once_with("user:alice", "notebook:proj", "admin")
    assert result["project_id"] == "notebook:proj"
    assert result["role"] == "admin"
