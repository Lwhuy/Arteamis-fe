from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from api import email_service, invitation_service
from api.deps import get_identity, require_role
from api.models import (
    AcceptInvitationResponse,
    InvitationCreate,
    InvitationCreateResponse,
    InvitationPreviewResponse,
    InvitationResponse,
)
from api.security import AuthContext
from open_notebook.domain.invitation import Invitation
from open_notebook.domain.notebook import Project
from open_notebook.domain.workspace import Workspace
from open_notebook.exceptions import NotFoundError

router = APIRouter()


async def _project_name(project_id: Optional[str]) -> Optional[str]:
    if not project_id:
        return None
    try:
        return (await Project.get(project_id)).name
    except NotFoundError:
        return None


async def _workspace_name(workspace_id: str) -> str:
    try:
        return (await Workspace.get(workspace_id)).name
    except NotFoundError:
        return workspace_id


def _to_response(inv: Invitation, project_name: Optional[str]) -> InvitationResponse:
    return InvitationResponse(
        id=str(inv.id or ""),
        email=inv.email,
        role=inv.role,
        project_id=inv.project,
        project_name=project_name,
        status=inv.status,
        invited_by=inv.invited_by,
        expires_at=str(inv.expires_at),
        created=str(inv.created or ""),
    )


def _assert_workspace_scope(ctx: AuthContext, workspace_id: str) -> None:
    # The workspace-scoped token must match the path workspace; else hide existence.
    if ctx.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Workspace not found")


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=InvitationCreateResponse,
    status_code=201,
)
async def create_invitation(
    workspace_id: str,
    body: InvitationCreate,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    _assert_workspace_scope(ctx, workspace_id)
    invitation, raw_token = await invitation_service.create_invitation(
        workspace_id=workspace_id,
        inviter_user_id=ctx.user_id,
        email=body.email,
        role=body.role,
        project_id=body.project_id,
    )
    project_name = await _project_name(invitation.project)
    invite_url = invitation_service.build_invite_url(raw_token)
    workspace_name = await _workspace_name(workspace_id)
    try:
        email_sent = await email_service.send_invite_email(
            invitation.email, invite_url, workspace_name, project_name
        )
    except Exception as e:  # pragma: no cover - defensive; email_service already swallows
        logger.warning(f"Invite email send raised unexpectedly: {e}")
        email_sent = False
    return InvitationCreateResponse(
        invitation=_to_response(invitation, project_name),
        email_sent=email_sent,
        share_url=None if email_sent else invite_url,
    )


@router.get(
    "/workspaces/{workspace_id}/invitations",
    response_model=List[InvitationResponse],
)
async def list_invitations(
    workspace_id: str,
    status: Optional[str] = Query(None, description="Filter by status, e.g. pending"),
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    _assert_workspace_scope(ctx, workspace_id)
    invitations = await invitation_service.list_invitations(workspace_id, status)
    return [_to_response(inv, await _project_name(inv.project)) for inv in invitations]


@router.post(
    "/workspaces/{workspace_id}/invitations/{invitation_id}/revoke",
    response_model=InvitationResponse,
)
async def revoke_invitation(
    workspace_id: str,
    invitation_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    _assert_workspace_scope(ctx, workspace_id)
    inv = await invitation_service.revoke_invitation(workspace_id, invitation_id)
    return _to_response(inv, await _project_name(inv.project))


@router.get("/invitations/{token}", response_model=InvitationPreviewResponse)
async def preview_invitation(token: str):
    """Public: preview an invitation by its raw token (no secrets returned)."""
    data = await invitation_service.preview_invitation(token)
    return InvitationPreviewResponse(**data)


@router.post("/invitations/{token}/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(token: str, user_id: str = Depends(get_identity)):
    data = await invitation_service.accept_invitation(token, user_id)
    return AcceptInvitationResponse(**data)
