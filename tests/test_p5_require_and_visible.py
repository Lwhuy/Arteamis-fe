from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api import source_permissions as sp
from api.source_permissions import (
    PermissionContext,
    require_mutate_source,
    require_view_source,
    visible_source_ids,
)
from open_notebook.domain.notebook import Source
from open_notebook.exceptions import NotFoundError


def _ctx(role="member"):
    return PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role=role)


@pytest.mark.asyncio
async def test_require_view_missing_is_404():
    with patch.object(Source, "get", new=AsyncMock(side_effect=NotFoundError("x"))):
        with pytest.raises(HTTPException) as e:
            await require_view_source("source:missing", _ctx())
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_require_view_deny_is_404():
    src = Source(id="source:1", title="t", owner="user:z", scope="personal")
    with patch.object(Source, "get", new=AsyncMock(return_value=src)):
        with patch.object(sp, "can_view_source", new=AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as e:
                await require_view_source("source:1", _ctx())
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_require_mutate_viewable_but_not_mutable_is_403():
    src = Source(id="source:1", title="t", owner="user:z", scope="company")
    with patch.object(Source, "get", new=AsyncMock(return_value=src)):
        with patch.object(sp, "can_view_source", new=AsyncMock(return_value=True)):
            with patch.object(sp, "can_mutate_source", new=AsyncMock(return_value=False)):
                with pytest.raises(HTTPException) as e:
                    await require_mutate_source("source:1", _ctx())
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_require_mutate_not_viewable_is_404():
    src = Source(id="source:1", title="t", owner="user:z", scope="personal")
    with patch.object(Source, "get", new=AsyncMock(return_value=src)):
        with patch.object(sp, "can_view_source", new=AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as e:
                await require_mutate_source("source:1", _ctx())
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_visible_source_ids_admin_branch_is_workspace_wide_and_deduped():
    ctx = _ctx(role="admin")
    with patch(
        "api.source_permissions.repo_query",
        new=AsyncMock(return_value=["source:a", "source:a", "source:b"]),
    ) as m:
        ids = await visible_source_ids(ctx)
    assert ids == ["source:a", "source:b"]
    assert "in.owner" not in m.call_args.args[0]  # admin branch = no per-user predicate


@pytest.mark.asyncio
async def test_visible_source_ids_member_branch_has_all_three_scope_predicates():
    ctx = _ctx(role="member")
    with patch(
        "api.source_permissions.repo_query", new=AsyncMock(return_value=[])
    ) as m:
        await visible_source_ids(ctx, project_id="notebook:p1")
    q = m.call_args.args[0]
    assert "in.owner = $user" in q
    assert "in.scope = 'company'" in q
    assert "in.scope = 'project'" in q
    assert "out = $project" in q
