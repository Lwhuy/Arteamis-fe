"""Unit tests for api/workspace_service.py (repo layer mocked)."""

from unittest.mock import AsyncMock, patch

import pytest

from api.workspace_service import (
    create_workspace,
    ensure_personal_workspace,
    get_membership,
    list_memberships,
    slugify,
)
from open_notebook.domain.workspace import Membership, Workspace
from open_notebook.exceptions import DuplicateResourceError


def test_slugify_basic():
    assert slugify("Acme Inc.") == "acme-inc"
    assert slugify("  Hello   World!! ") == "hello-world"
    assert slugify("") == "workspace"
    assert slugify("!!!") == "workspace"
    assert len(slugify("x" * 100)) == 40


@pytest.mark.asyncio
@patch("api.workspace_service.repo_query", new_callable=AsyncMock)
async def test_ensure_personal_workspace_creates_when_absent(mock_query):
    # 1st call: no existing personal workspace found. 2nd call (post-create,
    # membership existence check): no existing membership found either.
    mock_query.side_effect = [[], []]
    with patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock) as mock_create:
        mock_create.side_effect = [
            [{
                "id": "workspace:p1",
                "name": "Personal",
                "slug": "personal-1",
                "kind": "personal",
                "owner": "user:1",
                "created": "2026-07-11T00:00:00Z",
                "updated": "2026-07-11T00:00:00Z",
            }],
            [{
                "id": "membership:1",
                "user": "user:1",
                "workspace": "workspace:p1",
                "role": "owner",
                "status": "active",
            }],
        ]
        workspace = await ensure_personal_workspace("user:1")
    assert workspace.id == "workspace:p1"
    assert workspace.kind == "personal"


@pytest.mark.asyncio
@patch("api.workspace_service.repo_query", new_callable=AsyncMock)
async def test_ensure_personal_workspace_idempotent_when_present(mock_query):
    mock_query.return_value = [{
        "id": "workspace:p1",
        "name": "Personal",
        "slug": "personal-1",
        "kind": "personal",
        "owner": "user:1",
    }]
    with patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock) as mock_create:
        workspace = await ensure_personal_workspace("user:1")
        mock_create.assert_not_awaited()  # no-op: nothing created on the 2nd call
    assert workspace.id == "workspace:p1"


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_workspace_creates_owner_membership(mock_create):
    # First repo_create -> workspace row; second -> membership row.
    mock_create.side_effect = [
        [{
            "id": "workspace:acme",
            "name": "Acme",
            "slug": "acme",
            "kind": "company",
            "owner": "user:1",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }],
        [{
            "id": "membership:1",
            "user": "user:1",
            "workspace": "workspace:acme",
            "role": "owner",
            "status": "active",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }],
    ]
    workspace, membership = await create_workspace("user:1", "Acme")
    assert workspace.id == "workspace:acme"
    assert workspace.kind == "company"
    assert workspace.slug == "acme"
    assert membership.role == "owner"
    assert membership.status == "active"


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_workspace_slug_collision_raises_duplicate(mock_create):
    mock_create.side_effect = RuntimeError(
        "Database index `idx_workspace_slug` already contains 'acme'"
    )
    with pytest.raises(DuplicateResourceError):
        await create_workspace("user:1", "Acme")


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_delete", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_workspace_orphan_cleanup_on_membership_failure(
    mock_create, mock_delete
):
    mock_create.side_effect = [
        [{"id": "workspace:acme", "name": "Acme", "slug": "acme", "kind": "company", "owner": "user:1"}],
        RuntimeError("boom"),
    ]
    with pytest.raises(RuntimeError):
        await create_workspace("user:1", "Acme")
    mock_delete.assert_awaited()  # workspace was cleaned up


@pytest.mark.asyncio
@patch("api.workspace_service.repo_query", new_callable=AsyncMock)
async def test_list_memberships_maps_rows_including_kind(mock_query):
    mock_query.return_value = [
        {
            "role": "owner",
            "workspace": {
                "id": "workspace:p1",
                "name": "Personal",
                "slug": "personal-1",
                "kind": "personal",
                "created": "2026-07-11T00:00:00Z",
                "updated": "2026-07-11T00:00:00Z",
            },
        },
        {
            "role": "owner",
            "workspace": {
                "id": "workspace:acme",
                "name": "Acme",
                "slug": "acme",
                "kind": "company",
                "created": "2026-07-11T00:00:00Z",
                "updated": "2026-07-11T00:00:00Z",
            },
        },
    ]
    rows = await list_memberships("user:1")
    assert rows == [
        {
            "workspace_id": "workspace:p1",
            "name": "Personal",
            "slug": "personal-1",
            "kind": "personal",
            "role": "owner",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        },
        {
            "workspace_id": "workspace:acme",
            "name": "Acme",
            "slug": "acme",
            "kind": "company",
            "role": "owner",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        },
    ]
    # Isolation: the query filters by the caller's user id.
    assert "WHERE user = $user" in mock_query.await_args.args[0]


@pytest.mark.asyncio
@patch("api.workspace_service.repo_query", new_callable=AsyncMock)
async def test_get_membership_returns_none_when_absent(mock_query):
    mock_query.return_value = []
    assert await get_membership("user:1", "workspace:acme") is None


@pytest.mark.asyncio
@patch("api.workspace_service.repo_query", new_callable=AsyncMock)
async def test_get_membership_returns_membership(mock_query):
    mock_query.return_value = [{
        "id": "membership:1",
        "user": "user:1",
        "workspace": "workspace:acme",
        "role": "member",
        "status": "active",
    }]
    m = await get_membership("user:1", "workspace:acme")
    assert isinstance(m, Membership)
    assert m.role == "member"
