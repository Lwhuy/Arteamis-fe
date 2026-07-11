"""Shared FastAPI auth dependencies for the multi-tenancy layer.

Introduced by P2; P6 later extends this module with require_workspace /
get_request_context / ScopedRepository and reuses require_role unchanged.
"""

from dataclasses import dataclass
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.security import (
    AuthContext,
    decode_access_token,
    decode_identity_token,
)
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.database.scoping import ScopedRepository
from open_notebook.exceptions import AuthenticationError

# auto_error=False so a missing header raises our AuthenticationError (-> 401 via
# the global handler) instead of HTTPBearer's default 403.
_bearer = HTTPBearer(auto_error=False)


async def get_identity(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    """user_id from an identity OR workspace-scoped access token (pre-workspace dep)."""
    if creds is None:
        raise AuthenticationError("Missing authorization header")
    try:
        return decode_identity_token(creds.credentials)
    except AuthenticationError:
        raise
    except Exception as e:  # jose errors etc.
        raise AuthenticationError(f"Invalid token: {e}")


async def get_auth_context(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AuthContext:
    """Require a workspace-scoped access token; 401 for an identity-only token."""
    if creds is None:
        raise AuthenticationError("Missing authorization header")
    try:
        ctx = decode_access_token(creds.credentials)
    except AuthenticationError:
        raise
    except Exception as e:
        raise AuthenticationError(f"Invalid token: {e}")
    if ctx.workspace_id is None or ctx.role is None:
        raise AuthenticationError("A workspace-scoped access token is required")
    return ctx


def require_role(*roles: str):
    """Dependency factory: 403 unless the caller's token role is in `roles`.

    The role is baked into the access token at create/switch time and never
    read from a client-supplied value. Used by P3+ (e.g. project create).
    Applies uniformly to a personal or company workspace token — a personal
    workspace's sole member always carries role="owner".
    """
    allowed = set(roles)

    async def _dep(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if ctx.role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Requires role: {', '.join(sorted(allowed))}",
            )
        return ctx

    return _dep


# ==========================================================================
# P6 additions. get_identity / get_auth_context / require_role are P2's and
# are reused UNCHANGED above — do not redefine them here. None of this code
# reads workspace.kind: a personal-workspace request and a company-workspace
# request are indistinguishable at this layer, by design (Option A).
# ==========================================================================


def require_workspace(
    auth: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """Reject a token that carries no active workspace. The 403 gate that
    guarantees ScopedRepository always has a concrete workspace_id to filter
    on. Because signup auto-provisions a personal workspace, this is NOT a
    "has a company" check — it passes for every logged-in user by default,
    personal or company alike."""
    if not auth.workspace_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "No active workspace selected for this request",
        )
    return auth


async def get_request_context(
    auth: AuthContext = Depends(require_workspace),
) -> ScopedRepository:
    """The dependency every workspace-scoped router uses. Hands back a repository
    pre-bound to auth.workspace_id — callers physically cannot query another
    workspace, personal or company alike."""
    return ScopedRepository(
        workspace_id=auth.workspace_id, user_id=auth.user_id, role=auth.role
    )


@dataclass
class PermissionContext:
    """The request-context object P5's can_view_source/can_mutate_source bind to.

    workspace_role is the caller's active-workspace role from the token.
    project_role resolves a caller's role in a specific project via
    project_member, with workspace owner/admin escalating to project 'admin'
    (matches P5's expected semantics). This is ALSO how a personal workspace's
    sole owner resolves to project-admin: they are always workspace_role ==
    "owner", so they escalate without a project_member row ever needing to
    exist (and for personal workspaces, it never does) — one escalation path,
    not two."""

    user_id: str
    workspace_id: str
    workspace_role: str  # owner | admin | member

    async def project_role(self, project_id: str) -> Optional[str]:
        """Return 'admin' | 'member' | None for this caller in `project_id`.
        Workspace owner/admin escalate to project 'admin' without a membership
        row — this covers a personal workspace's sole owner automatically."""
        if self.workspace_role in ("owner", "admin"):
            return "admin"
        rows = await repo_query(
            # scoped-raw: PermissionContext is deliberately not a
            # ScopedRepository instance (see class docstring), so this can't
            # go through the ScopedRepository raw escape hatch — the query
            # itself filters natively by `workspace = $workspace`
            # (project_member has a native workspace column), so this is
            # workspace-filtered, not merely justified.
            "SELECT role FROM project_member "
            "WHERE user = $user AND project = $project "
            "AND workspace = $workspace AND status = 'active'",
            {
                "user": ensure_record_id(self.user_id),
                "project": ensure_record_id(project_id),
                "workspace": ensure_record_id(self.workspace_id),
            },
        )
        if rows:
            return rows[0].get("role")
        return None


async def get_permission_context(
    auth: AuthContext = Depends(require_workspace),
) -> PermissionContext:
    """P6's concrete PermissionContext, injected into P5's source-permission routers."""
    return PermissionContext(
        user_id=auth.user_id, workspace_id=auth.workspace_id, workspace_role=auth.role
    )


AuthDep = Annotated[AuthContext, Depends(require_workspace)]
CtxDep = Annotated[ScopedRepository, Depends(get_request_context)]
PermCtxDep = Annotated[PermissionContext, Depends(get_permission_context)]
