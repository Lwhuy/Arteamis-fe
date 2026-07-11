"""POST/GET /workspaces — create a company workspace, list caller's memberships.

Routers stay thin (per api/AGENTS.md); all business logic lives in
api/workspace_service.py. This module wires get_identity (Task 5) +
workspace_service (Task 3) + create_access_token (Task 4) together.
"""

from typing import List

from fastapi import APIRouter, Depends

from api.deps import get_identity
from api.models import TokenResponse, WorkspaceCreate, WorkspaceResponse
from api.security import create_access_token
from api.workspace_service import create_workspace, list_memberships

router = APIRouter()


@router.post("/workspaces", response_model=TokenResponse, status_code=201)
async def create_workspace_endpoint(
    body: WorkspaceCreate,
    user_id: str = Depends(get_identity),
) -> TokenResponse:
    """Create a company workspace; the caller becomes its owner.

    Open to any authenticated user (incl. one who has only ever used their
    personal workspace — you cannot require a role you do not yet have).
    ALWAYS creates kind="company" (WorkspaceCreate has no kind field). Re-mints
    a workspace-scoped `owner` access token so the very next request (P3
    project create) is scoped to the new workspace. A slug collision raises
    DuplicateResourceError -> 409 (global handler).
    """
    workspace, membership = await create_workspace(user_id, body.name, body.slug)
    access_token = create_access_token(
        user_id=user_id,
        workspace_id=workspace.id or "",
        role=membership.role,
    )
    return TokenResponse(
        access_token=access_token,
        active_workspace_id=workspace.id or "",
        role=membership.role,
    )


@router.get("/workspaces", response_model=List[WorkspaceResponse])
async def list_workspaces_endpoint(
    user_id: str = Depends(get_identity),
) -> List[WorkspaceResponse]:
    """List the caller's active memberships — always includes their personal workspace."""
    rows = await list_memberships(user_id)
    return [
        WorkspaceResponse(
            id=row["workspace_id"],
            name=row["name"],
            slug=row["slug"],
            kind=row["kind"],
            role=row["role"],
            created=row["created"],
            updated=row["updated"],
        )
        for row in rows
    ]
