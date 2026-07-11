# tests/test_deps_context.py
"""Unit tests for P6 additions to api/deps.py: require_workspace, get_request_context,
and PermissionContext.project_role (repo_query patched — no live DB)."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.deps import (
    PermissionContext,
    get_permission_context,
    get_request_context,
    require_workspace,
)
from api.security import AuthContext
from open_notebook.database.scoping import ScopedRepository


def _auth(workspace_id="workspace:A", role="owner"):
    return AuthContext(user_id="user:1", workspace_id=workspace_id, role=role)


def test_require_workspace_passes_with_active_workspace():
    assert require_workspace(_auth()) is not None


def test_require_workspace_403_without_workspace():
    with pytest.raises(HTTPException) as exc:
        require_workspace(_auth(workspace_id=None, role=None))
    assert exc.value.status_code == 403
    assert "No active workspace" in exc.value.detail


@pytest.mark.asyncio
async def test_get_request_context_returns_bound_scoped_repository():
    repo = await get_request_context(_auth())
    assert isinstance(repo, ScopedRepository)
    assert repo.workspace_id == "workspace:A"
    assert repo.user_id == "user:1"
    assert repo.role == "owner"


@pytest.mark.asyncio
async def test_project_role_escalates_workspace_owner_admin_to_project_admin():
    ctx = PermissionContext(user_id="user:1", workspace_id="workspace:A", workspace_role="admin")
    # No project_member query should be needed for workspace admin — returns "admin".
    with patch("api.deps.repo_query", new=AsyncMock(return_value=[])) as q:
        assert await ctx.project_role("notebook:p1") == "admin"
    q.assert_not_called()


@pytest.mark.asyncio
async def test_project_role_escalates_personal_workspace_owner_with_no_membership_row():
    """A personal workspace's sole member is always workspace_role='owner'. This
    must resolve to project-admin via the SAME escalation path as a company
    owner/admin — with zero project_member rows and zero branching on kind."""
    ctx = PermissionContext(user_id="user:1", workspace_id="workspace:personal-1", workspace_role="owner")
    with patch("api.deps.repo_query", new=AsyncMock(return_value=[])) as q:
        assert await ctx.project_role("notebook:solo-project") == "admin"
    q.assert_not_called()


@pytest.mark.asyncio
async def test_project_role_reads_project_member_for_plain_member():
    ctx = PermissionContext(user_id="user:2", workspace_id="workspace:A", workspace_role="member")
    with patch("api.deps.repo_query", new=AsyncMock(return_value=[{"role": "member"}])) as q:
        assert await ctx.project_role("notebook:p1") == "member"
    q.assert_called_once()
    query, params = q.call_args[0]
    assert "project_member" in query
    assert "workspace = $workspace" in query  # membership lookup is itself workspace-scoped


@pytest.mark.asyncio
async def test_project_role_none_when_not_a_member():
    ctx = PermissionContext(user_id="user:3", workspace_id="workspace:A", workspace_role="member")
    with patch("api.deps.repo_query", new=AsyncMock(return_value=[])):
        assert await ctx.project_role("notebook:p1") is None


@pytest.mark.asyncio
async def test_get_permission_context_maps_role_to_workspace_role():
    ctx = await get_permission_context(_auth(role="member"))
    assert ctx.workspace_role == "member"
    assert ctx.workspace_id == "workspace:A"
    assert ctx.user_id == "user:1"
