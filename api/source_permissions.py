"""Source scope/permission predicate (P5, v2 3-level scope).

All source authorization lives here so routers stay thin (api/AGENTS.md).

PermissionContext is shipped concrete by P5 so this module is runnable/testable
before P6 exists. P6 formalizes/relocates the SAME interface (user_id,
workspace_id, workspace_role, async project_role) -- keep them in sync.
"""
from typing import List, Optional

from fastapi import Depends, HTTPException

from api.deps import get_auth_context  # P2
from api.security import AuthContext  # P1
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Source
from open_notebook.exceptions import NotFoundError


class PermissionContext:
    """Request-scoped auth context P5 needs. P6 replaces the class body's origin
    but not its shape. `workspace_role` is always "owner" in a kind="personal"
    workspace (the sole member)."""

    def __init__(self, user_id: str, workspace_id: str, workspace_role: str):
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.workspace_role = workspace_role

    async def project_role(self, project_id: str) -> Optional[str]:
        """Caller's role on a project: 'admin'|'member'|None. Workspace
        owner/admin escalate to project admin everywhere in their workspace
        (this also covers personal-workspace projects, which have no
        project_member rows at all -- the escalation short-circuits before the
        query below ever runs)."""
        if self.workspace_role in ("owner", "admin"):
            return "admin"
        rows = await repo_query(
            "SELECT VALUE role FROM project_member "
            "WHERE user = $user AND project = $project AND status = 'active'",
            {
                "user": ensure_record_id(self.user_id),
                "project": ensure_record_id(project_id),
            },
        )
        return rows[0] if rows else None


async def get_permission_context(
    auth: AuthContext = Depends(get_auth_context),
) -> PermissionContext:
    """FastAPI dependency injected into every source-touching route."""
    return PermissionContext(
        user_id=str(auth.user_id),
        workspace_id=str(auth.workspace_id),
        workspace_role=str(auth.role),
    )


async def _source_workspaces(source: Source) -> List[str]:
    """Workspace ids owning this source, resolved via its referencing projects."""
    rows = await repo_query(
        "SELECT VALUE out.workspace FROM reference WHERE in = $source",
        {"source": ensure_record_id(source.id)},
    )
    return [str(w) for w in rows if w is not None]


async def _in_active_workspace(source: Source, ctx: PermissionContext) -> bool:
    return ctx.workspace_id in await _source_workspaces(source)


async def can_view_source(source: Source, ctx: PermissionContext) -> bool:
    # Workspace isolation (belt-and-braces with P6): must be referenced by a
    # project in the caller's active workspace, else treat as not-found.
    if not await _in_active_workspace(source, ctx):
        return False
    # Owner always sees their own source.
    if source.owner is not None and str(source.owner) == ctx.user_id:
        return True
    # Workspace owner/admin sees everything in the workspace, including
    # 'personal'-scope sources. In a kind="personal" workspace the sole member
    # is always "owner", so this branch alone makes the collapse-to-owner-only
    # behavior fall out naturally, with no kind-conditional code.
    if ctx.workspace_role in ("owner", "admin"):
        return True
    project_ids = await source.get_project_ids()
    # Project admin of any referencing project sees everything in it.
    for pid in project_ids:
        if await ctx.project_role(pid) == "admin":
            return True
    # 'company' scope: visible to every member of the active workspace, across
    # every project. No extra membership lookup needed -- _in_active_workspace
    # already proved same-workspace, and holding a PermissionContext for this
    # workspace_id already proves active membership in it.
    if source.scope == "company":
        return True
    # 'project' scope: any member (admin/member) of a referencing project.
    if source.scope == "project":
        for pid in project_ids:
            if await ctx.project_role(pid) in ("admin", "member"):
                return True
    return False


async def can_mutate_source(source: Source, ctx: PermissionContext) -> bool:
    if not await _in_active_workspace(source, ctx):
        return False
    if source.owner is not None and str(source.owner) == ctx.user_id:
        return True
    if ctx.workspace_role in ("owner", "admin"):
        return True
    for pid in await source.get_project_ids():
        if await ctx.project_role(pid) == "admin":
            return True
    return False


async def require_view_source(source_id: str, ctx: PermissionContext) -> Source:
    """Load + view-check. 404 if missing OR view-denied (no existence oracle)."""
    try:
        source = await Source.get(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    if not await can_view_source(source, ctx):
        raise HTTPException(status_code=404, detail="Source not found")
    return source


async def require_mutate_source(source_id: str, ctx: PermissionContext) -> Source:
    """Load + mutate-check. 404 if not even viewable; 403 if viewable but not mutable."""
    try:
        source = await Source.get(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    if not await can_view_source(source, ctx):
        raise HTTPException(status_code=404, detail="Source not found")
    if not await can_mutate_source(source, ctx):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to modify this source",
        )
    return source


async def visible_source_ids(
    ctx: PermissionContext, project_id: Optional[str] = None
) -> List[str]:
    """Source ids in the caller's workspace (optionally one project) the caller
    may VIEW, across all three scopes. Single parameterized query (no N+1);
    backs GET /sources + search filters.

    Workspace owner/admin: every source in the workspace (any scope).
    Otherwise: owner's own sources, plus every 'company'-scope source in the
    workspace (no membership predicate needed — same-workspace is sufficient),
    plus every source of any project they admin, plus 'project'-scope sources
    of any project they are a plain member of.
    """
    params = {
        "workspace": ensure_record_id(ctx.workspace_id),
        "user": ensure_record_id(ctx.user_id),
    }
    project_filter = ""
    if project_id is not None:
        params["project"] = ensure_record_id(project_id)
        project_filter = " AND out = $project"

    if ctx.workspace_role in ("owner", "admin"):
        query = (
            "SELECT VALUE in FROM reference "
            "WHERE out.workspace = $workspace" + project_filter
        )
    else:
        query = (
            "SELECT VALUE in FROM reference "
            "WHERE out.workspace = $workspace" + project_filter + " AND ("
            "in.owner = $user "
            "OR in.scope = 'company' "
            "OR out IN (SELECT VALUE project FROM project_member "
            "WHERE user = $user AND role = 'admin' AND status = 'active') "
            "OR (in.scope = 'project' AND out IN (SELECT VALUE project "
            "FROM project_member WHERE user = $user AND status = 'active'))"
            ")"
        )
    rows = await repo_query(query, params)
    seen: List[str] = []
    for r in rows:
        s = str(r)
        if s not in seen:
            seen.append(s)
    return seen
