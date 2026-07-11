"""Unit tests for the auth dependencies in api/deps.py."""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.deps import get_auth_context, get_identity, require_role
from api.security import (
    AuthContext,
    create_access_token,
    create_identity_token,
)
from open_notebook.exceptions import AuthenticationError


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    # Function-scoped and auto-reverted so this test's JWT_SECRET never leaks
    # into other test modules (see tests/test_p2_access_token.py for the same
    # pattern).
    monkeypatch.setenv("JWT_SECRET", "test-secret-p2-deps")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.asyncio
async def test_get_identity_accepts_identity_token():
    token = create_identity_token("user:abc")
    assert await get_identity(_creds(token)) == "user:abc"


@pytest.mark.asyncio
async def test_get_identity_accepts_access_token_too():
    # A caller with a workspace-scoped token (the common case post-P2) must
    # also be able to hit identity-level endpoints like POST /workspaces.
    token = create_access_token("user:abc", "workspace:xyz", "owner")
    assert await get_identity(_creds(token)) == "user:abc"


@pytest.mark.asyncio
async def test_get_identity_missing_header_401():
    with pytest.raises(AuthenticationError):
        await get_identity(None)


@pytest.mark.asyncio
async def test_get_auth_context_requires_workspace_scope():
    # An identity-only token has no workspace_id -> get_auth_context rejects it.
    token = create_identity_token("user:abc")
    with pytest.raises(AuthenticationError):
        await get_auth_context(_creds(token))


@pytest.mark.asyncio
async def test_get_auth_context_accepts_access_token():
    token = create_access_token("user:abc", "workspace:xyz", "owner")
    ctx = await get_auth_context(_creds(token))
    assert ctx.workspace_id == "workspace:xyz"
    assert ctx.role == "owner"


@pytest.mark.asyncio
async def test_require_role_allows_matching_role():
    dep = require_role("owner", "admin")
    ctx = AuthContext(user_id="user:abc", workspace_id="workspace:xyz", role="owner")
    assert await dep(ctx) is ctx


@pytest.mark.asyncio
async def test_require_role_forbids_other_role():
    dep = require_role("owner", "admin")
    ctx = AuthContext(user_id="user:abc", workspace_id="workspace:xyz", role="member")
    with pytest.raises(HTTPException) as exc:
        await dep(ctx)
    assert exc.value.status_code == 403
