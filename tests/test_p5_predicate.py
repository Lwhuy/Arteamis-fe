"""Permission predicate logic (P5, v2 3-scope). Uses a hand-built
PermissionContext; the source's project ids, workspace resolution, and
project_role are mocked."""
from unittest.mock import AsyncMock, patch

import pytest

from api.source_permissions import (
    PermissionContext,
    can_mutate_source,
    can_view_source,
)
from open_notebook.domain.notebook import Source


def _ctx(user="user:u1", workspace="workspace:w1", role="member"):
    return PermissionContext(user_id=user, workspace_id=workspace, workspace_role=role)


def _source(owner=None, scope="project", sid="source:s1"):
    return Source(id=sid, title="t", owner=owner, scope=scope)


@pytest.fixture
def in_workspace():
    # every predicate first resolves the source's workspace via the reference edge
    with patch(
        "api.source_permissions.repo_query",
        new=AsyncMock(return_value=["workspace:w1"]),
    ) as m:
        yield m


@pytest.mark.asyncio
async def test_owner_can_view_and_mutate_personal(in_workspace):
    ctx = _ctx()
    src = _source(owner="user:u1", scope="personal")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value=None)
        assert await can_view_source(src, ctx) is True
        assert await can_mutate_source(src, ctx) is True


@pytest.mark.asyncio
async def test_workspace_admin_can_view_and_mutate_others_personal(in_workspace):
    ctx = _ctx(user="user:u2", role="admin")
    src = _source(owner="user:u1", scope="personal")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value="admin")
        assert await can_view_source(src, ctx) is True
        assert await can_mutate_source(src, ctx) is True


@pytest.mark.asyncio
async def test_project_admin_can_view_and_mutate_personal(in_workspace):
    ctx = _ctx(user="user:u2", role="member")
    src = _source(owner="user:u1", scope="personal")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value="admin")
        assert await can_view_source(src, ctx) is True
        assert await can_mutate_source(src, ctx) is True


@pytest.mark.asyncio
async def test_member_view_project_but_not_personal_and_never_mutate(in_workspace):
    ctx = _ctx(user="user:u2", role="member")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value="member")
        assert await can_view_source(_source(owner="user:u1", scope="project"), ctx) is True
        assert await can_view_source(_source(owner="user:u1", scope="personal"), ctx) is False
        assert await can_mutate_source(_source(owner="user:u1", scope="project"), ctx) is False


@pytest.mark.asyncio
async def test_workspace_member_outside_project_sees_only_company_scope(in_workspace):
    # Same workspace, but NOT a member of the project the source is referenced by.
    ctx = _ctx(user="user:u3", role="member")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value=None)
        assert await can_view_source(_source(owner="user:u1", scope="company"), ctx) is True
        assert await can_view_source(_source(owner="user:u1", scope="project"), ctx) is False
        assert await can_view_source(_source(owner="user:u1", scope="personal"), ctx) is False
        # Can view company scope, but cannot mutate it (not owner/admin).
        assert await can_mutate_source(_source(owner="user:u1", scope="company"), ctx) is False


@pytest.mark.asyncio
async def test_outsider_other_workspace_denied():
    ctx = _ctx(user="user:x", workspace="workspace:OTHER", role="member")
    src = _source(owner="user:u1", scope="company")
    with patch("api.source_permissions.repo_query", new=AsyncMock(return_value=["workspace:w1"])):
        with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
            ctx.project_role = AsyncMock(return_value=None)
            assert await can_view_source(src, ctx) is False
            assert await can_mutate_source(src, ctx) is False


@pytest.mark.asyncio
async def test_personal_workspace_solo_owner_sees_all_scopes(in_workspace):
    # A kind="personal" workspace's sole member is always "owner" -> the
    # workspace_role escalation branch (step 3) allows every scope for the
    # solo owner, with no kind-conditional code needed.
    ctx = _ctx(user="user:solo", role="owner")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value=None)
        for scope in ("personal", "project", "company"):
            src = _source(owner="user:solo", scope=scope)
            assert await can_view_source(src, ctx) is True
            assert await can_mutate_source(src, ctx) is True
