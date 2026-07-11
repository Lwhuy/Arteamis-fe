"""Invitation lifecycle: create (workspace/project), accept (state machine), revoke.

Routers stay thin (api/AGENTS.md); all validation and DB work lives here. Status
codes without a typed-exception mapping (403/409/410) are raised as HTTPException
per the P4 spec; 404/400 use the typed exceptions the global handlers already map.

v2 guard: invitations only ever target a kind="company" workspace. A
kind="personal" workspace always has exactly one member (its owner) and is never
invitable — create_invitation 403s before any other validation when the target
workspace is personal, regardless of the caller's role.
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.invitation import Invitation
from open_notebook.domain.notebook import Project, ProjectMember
from open_notebook.domain.user import User
from open_notebook.domain.workspace import Membership, Workspace
from open_notebook.exceptions import InvalidInputError, NotFoundError

INVITE_TTL_DAYS = 7


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def build_invite_url(raw_token: str) -> str:
    base = os.getenv("OPEN_NOTEBOOK_APP_URL", "http://localhost:3000").rstrip("/")
    return f"{base}/invite/{raw_token}"


async def _get_workspace(workspace_id: str) -> Workspace:
    try:
        return await Workspace.get(workspace_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found")


async def _existing_pending(
    workspace_id: str, email: str, project_id: Optional[str]
) -> Optional[Invitation]:
    """The pending invite for the same (workspace, email, project) scope, if any."""
    result = await repo_query(
        """
        SELECT * FROM invitation
        WHERE workspace = $workspace AND email = $email AND project = $project AND status = 'pending'
        LIMIT 1
        """,
        {
            "workspace": ensure_record_id(workspace_id),
            "email": email,
            "project": ensure_record_id(project_id) if project_id else None,
        },
    )
    return Invitation(**result[0]) if result else None


async def _email_has_active_membership(workspace_id: str, email: str) -> bool:
    result = await repo_query(
        """
        SELECT id FROM membership
        WHERE workspace = $workspace AND status = 'active'
          AND user IN (SELECT VALUE id FROM user WHERE email = $email)
        LIMIT 1
        """,
        {"workspace": ensure_record_id(workspace_id), "email": email},
    )
    return bool(result)


async def _email_has_active_project_member(project_id: str, email: str) -> bool:
    result = await repo_query(
        """
        SELECT id FROM project_member
        WHERE project = $project AND status = 'active'
          AND user IN (SELECT VALUE id FROM user WHERE email = $email)
        LIMIT 1
        """,
        {"project": ensure_record_id(project_id), "email": email},
    )
    return bool(result)


async def create_invitation(
    workspace_id: str,
    inviter_user_id: str,
    email: str,
    role: str,
    project_id: Optional[str] = None,
) -> tuple[Invitation, str]:
    workspace = await _get_workspace(workspace_id)
    if workspace.kind != "company":
        # Personal workspaces are solo tenants (exactly one member, ever) — this
        # is a permanent data-model rule, not a role check, so it applies to
        # every caller including the personal workspace's own owner.
        raise HTTPException(
            status_code=403, detail="Cannot invite members into a personal workspace"
        )

    email = email.strip().lower()
    if role not in ("admin", "member"):
        raise InvalidInputError("role must be 'admin' or 'member'")

    if project_id is None:
        # Workspace invite.
        if await _email_has_active_membership(workspace_id, email):
            raise HTTPException(
                status_code=409, detail="User is already a member of this workspace"
            )
    else:
        # Project invite: the project must belong to this workspace.
        try:
            project = await Project.get(project_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.workspace != workspace_id:
            raise HTTPException(status_code=404, detail="Project not found")
        if await _email_has_active_project_member(project_id, email):
            raise HTTPException(
                status_code=409, detail="User is already a member of this project"
            )

    raw, token_hash = generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)

    existing = await _existing_pending(workspace_id, email, project_id)
    if existing is not None:
        # Rotate the token/expiry on the existing row (old raw token stops resolving).
        existing.token_hash = token_hash
        existing.expires_at = expires_at
        existing.role = role
        existing.invited_by = inviter_user_id
        existing.status = "pending"
        await existing.save()
        return existing, raw

    invitation = Invitation(
        workspace=workspace_id,
        email=email,
        role=role,
        project=project_id,
        token_hash=token_hash,
        status="pending",
        invited_by=inviter_user_id,
        expires_at=expires_at,
    )
    await invitation.save()
    return invitation, raw


async def _upsert_workspace_membership(user_id: str, workspace_id: str, role: str) -> None:
    rows = await repo_query(
        "SELECT * FROM membership WHERE user = $user AND workspace = $workspace LIMIT 1",
        {"user": ensure_record_id(user_id), "workspace": ensure_record_id(workspace_id)},
    )
    if not rows:
        await Membership(user=user_id, workspace=workspace_id, role=role, status="active").save()
        return
    membership = Membership(**rows[0])
    if membership.status != "active":
        membership.status = "active"
        if role == "admin" and membership.role == "member":
            membership.role = "admin"
        await membership.save()
    # Already active: idempotent — never downgrade an existing higher role.


async def _upsert_project_member(user_id: str, project_id: str, role: str) -> None:
    rows = await repo_query(
        "SELECT * FROM project_member WHERE user = $user AND project = $project LIMIT 1",
        {"user": ensure_record_id(user_id), "project": ensure_record_id(project_id)},
    )
    if not rows:
        await ProjectMember(user=user_id, project=project_id, role=role, status="active").save()
        return
    member = ProjectMember(**rows[0])
    member.status = "active"
    member.role = role
    await member.save()


async def accept_invitation(raw_token: str, user_id: str) -> dict:
    inv = await Invitation.get_by_token_hash(hash_token(raw_token))
    if inv is None:
        raise NotFoundError("Invitation not found")
    if inv.status != "pending":
        raise HTTPException(status_code=410, detail="This invitation is no longer valid")
    if inv.is_expired():
        inv.status = "expired"
        await inv.save()
        raise HTTPException(status_code=410, detail="This invitation has expired")

    user = await User.get(user_id)  # NotFoundError -> 404
    if (user.email or "").lower() != inv.email.lower():
        raise HTTPException(
            status_code=403, detail="This invitation was sent to a different email."
        )

    if inv.project is None:
        # Workspace invite: activate the workspace membership with the invited role.
        await _upsert_workspace_membership(user_id, inv.workspace, inv.role)
        result_role = inv.role
    else:
        # Project invite: ensure a workspace-shell membership, then the project member.
        await _upsert_workspace_membership(user_id, inv.workspace, "member")
        await _upsert_project_member(user_id, inv.project, inv.role)
        result_role = inv.role

    inv.status = "accepted"
    await inv.save()
    return {
        "workspace_id": inv.workspace,
        "role": result_role,
        "project_id": inv.project,
        "membership_status": "active",
    }


async def revoke_invitation(workspace_id: str, invitation_id: str) -> Invitation:
    try:
        inv = await Invitation.get(invitation_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if inv.workspace != workspace_id:
        # Hide cross-tenant existence.
        raise HTTPException(status_code=404, detail="Invitation not found")
    inv.status = "revoked"
    await inv.save()
    return inv


async def list_invitations(workspace_id: str, status: Optional[str] = None) -> list[Invitation]:
    if status is not None and status not in ("pending", "accepted", "revoked", "expired"):
        raise InvalidInputError("Invalid status filter")
    if status:
        rows = await repo_query(
            "SELECT * FROM invitation WHERE workspace = $workspace AND status = $status ORDER BY created DESC",
            {"workspace": ensure_record_id(workspace_id), "status": status},
        )
    else:
        rows = await repo_query(
            "SELECT * FROM invitation WHERE workspace = $workspace ORDER BY created DESC",
            {"workspace": ensure_record_id(workspace_id)},
        )
    return [Invitation(**r) for r in rows]


async def preview_invitation(raw_token: str) -> dict:
    inv = await Invitation.get_by_token_hash(hash_token(raw_token))
    if inv is None:
        raise NotFoundError("Invitation not found")
    if inv.status != "pending" or inv.is_expired():
        # Never leak secrets (token_hash / invited_by); 410 = expired/revoked/used.
        raise HTTPException(status_code=410, detail="This invitation is no longer valid")

    workspace = await Workspace.get(inv.workspace)
    project_name = None
    if inv.project is not None:
        try:
            project_name = (await Project.get(inv.project)).name
        except NotFoundError:
            project_name = None
    return {
        "workspace_name": workspace.name,
        "role": inv.role,
        "email": inv.email,
        "project_name": project_name,
        "status": inv.status,
        "expired": False,
    }
