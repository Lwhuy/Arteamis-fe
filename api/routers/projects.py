from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from api.deps import get_auth_context, require_role
from api.models import (
    ProjectCreate,
    ProjectDeletePreview,
    ProjectDeleteResponse,
    ProjectResponse,
    ProjectUpdate,
    RecentlyViewedResponse,
)
from api.security import AuthContext
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Project, Source
from open_notebook.exceptions import InvalidInputError, NotFoundError

router = APIRouter()

_ALLOWED_ORDER_FIELDS = {"name", "created", "updated"}
_ALLOWED_ORDER_DIRECTIONS = {"asc", "desc"}


def _validate_order_by(order_by: str) -> str:
    parts = order_by.strip().lower().split()
    if len(parts) == 1 and parts[0] in _ALLOWED_ORDER_FIELDS:
        return parts[0]
    if (
        len(parts) == 2
        and parts[0] in _ALLOWED_ORDER_FIELDS
        and parts[1] in _ALLOWED_ORDER_DIRECTIONS
    ):
        return f"{parts[0]} {parts[1]}"
    raise HTTPException(
        status_code=400,
        detail=(
            f"Invalid order_by: '{order_by}'. Allowed fields: "
            f"{', '.join(sorted(_ALLOWED_ORDER_FIELDS))}; directions: asc, desc"
        ),
    )


def _project_response_from_row(row: dict) -> ProjectResponse:
    return ProjectResponse(
        id=str(row.get("id", "")),
        name=row.get("name", ""),
        description=row.get("description", ""),
        archived=row.get("archived", False),
        created=str(row.get("created", "")),
        updated=str(row.get("updated", "")),
        source_count=row.get("source_count", 0),
        note_count=row.get("note_count", 0),
        workspace=str(row["workspace"]) if row.get("workspace") else None,
        owner=str(row["owner"]) if row.get("owner") else None,
        default_source_scope=row.get("default_source_scope", "personal"),
        promoted_from=str(row["promoted_from"]) if row.get("promoted_from") else None,
    )


@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    archived: Optional[bool] = Query(None, description="Filter by archived status"),
    order_by: str = Query("updated desc", description="Order by field and direction"),
    ctx: AuthContext = Depends(get_auth_context),
):
    """List projects for the caller's active workspace (personal or company)."""
    validated_order_by = _validate_order_by(order_by)
    query = f"""
        SELECT *,
        count(<-reference.in) as source_count,
        count(<-artifact.in) as note_count
        FROM notebook
        WHERE workspace = $workspace_id
        ORDER BY {validated_order_by}
    """
    try:
        result = await repo_query(
            query, {"workspace_id": ensure_record_id(ctx.workspace_id)}
        )
    except Exception as e:
        logger.error(f"Error fetching projects: {e}")
        raise HTTPException(status_code=500, detail="Error fetching projects")

    if archived is not None:
        result = [p for p in result if p.get("archived") == archived]
    return [_project_response_from_row(p) for p in result]


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    """Create a project in the caller's active workspace.

    require_role("owner","admin") gates a company workspace's plain members
    out, and naturally lets a personal-workspace owner create freely: P2's
    invariant is that a personal workspace has exactly one membership row and
    it is always role="owner", so no separate personal-workspace code path is
    needed here.
    """
    try:
        project = Project(
            name=body.name,
            description=body.description,
            workspace=ctx.workspace_id,
            owner=ctx.user_id,
            default_source_scope=body.default_source_scope or "personal",
        )
        # Called as Project.save(project) (not project.save()) so that when a
        # test patches Project.save with a bare AsyncMock (no autospec), the
        # instance is still passed through explicitly as `self` to the
        # side_effect. Equivalent to project.save() in production.
        await Project.save(project)
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        raise HTTPException(status_code=500, detail="Error creating project")

    # Seed the creator as the sole admin project_member. This row is only ever
    # consulted for authorization when the workspace is kind="company" and P4's
    # invite flow adds more members; for a personal project it is a harmless
    # no-op since ctx.role == "owner" already authorizes everything.
    try:
        await repo_query(
            "CREATE project_member SET project = $project, user = $user, "
            "role = 'admin', status = 'active'",
            {
                "project": ensure_record_id(project.id),
                "user": ensure_record_id(ctx.user_id),
            },
        )
    except Exception as e:
        logger.warning(f"Failed to seed admin member for project {project.id}: {e}")

    return ProjectResponse(
        id=project.id or "",
        name=project.name,
        description=project.description,
        archived=project.archived or False,
        created=str(project.created),
        updated=str(project.updated),
        source_count=0,
        note_count=0,
        workspace=ctx.workspace_id,
        owner=ctx.user_id,
        default_source_scope=project.default_source_scope,
        promoted_from=project.promoted_from,
    )


async def _load_project_in_workspace(project_id: str, ctx: AuthContext) -> Project:
    """Load a project and 404 unless it belongs to the caller's active workspace.

    Returning 404 (not 403) for another workspace's project hides its existence
    across tenants — including across personal vs. company workspace boundaries.
    """
    try:
        project = await Project.get(project_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.workspace != ctx.workspace_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _authorize_project_write(project: Project, ctx: AuthContext) -> None:
    """Workspace owner/admin may write any project; otherwise the caller must be
    a project admin (active project_member row with role='admin').

    In a personal workspace ctx.role is always "owner" (P2 invariant), so this
    always short-circuits on the first branch and project_member is never
    queried for a personal project.
    """
    if ctx.role in {"owner", "admin"}:
        return
    rows = await repo_query(
        "SELECT id FROM project_member WHERE project = $project AND user = $user "
        "AND role = 'admin' AND status = 'active'",
        {
            "project": ensure_record_id(project.id),
            "user": ensure_record_id(ctx.user_id),
        },
    )
    if not rows:
        raise HTTPException(status_code=403, detail="Requires project admin")


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str, ctx: AuthContext = Depends(get_auth_context)
):
    await _load_project_in_workspace(project_id, ctx)
    query = """
        SELECT *,
        count(<-reference.in) as source_count,
        count(<-artifact.in) as note_count
        FROM $project_id
    """
    result = await repo_query(
        query, {"project_id": ensure_record_id(project_id)}
    )
    if not result:
        raise HTTPException(status_code=404, detail="Project not found")
    # Best-effort write-on-read stamp; never fail a read.
    try:
        await repo_query(
            "UPDATE $project_id SET last_viewed_at = time::now();",
            {"project_id": ensure_record_id(project_id)},
        )
    except Exception as e:
        logger.warning(f"Failed to stamp last_viewed_at for project {project_id}: {e}")
    return _project_response_from_row(result[0])


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    ctx: AuthContext = Depends(get_auth_context),
):
    project = await _load_project_in_workspace(project_id, ctx)
    await _authorize_project_write(project, ctx)

    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.archived is not None:
        project.archived = body.archived
    if body.default_source_scope is not None:
        project.default_source_scope = body.default_source_scope

    try:
        # See create_project: called unbound so a bare-AsyncMock patch in
        # tests still receives the instance explicitly as `self`.
        await Project.save(project)
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = await repo_query(
        """
        SELECT *,
        count(<-reference.in) as source_count,
        count(<-artifact.in) as note_count
        FROM $project_id
        """,
        {"project_id": ensure_record_id(project_id)},
    )
    if result:
        return _project_response_from_row(result[0])
    return _project_response_from_row(
        {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "archived": project.archived,
            "created": project.created,
            "updated": project.updated,
            "workspace": project.workspace,
            "owner": project.owner,
            "default_source_scope": project.default_source_scope,
            "promoted_from": project.promoted_from,
        }
    )


@router.get(
    "/projects/{project_id}/delete-preview", response_model=ProjectDeletePreview
)
async def get_project_delete_preview(
    project_id: str, ctx: AuthContext = Depends(get_auth_context)
):
    project = await _load_project_in_workspace(project_id, ctx)
    await _authorize_project_write(project, ctx)
    preview = await project.get_delete_preview()
    return ProjectDeletePreview(
        project_id=str(project.id),
        project_name=project.name,
        note_count=preview["note_count"],
        exclusive_source_count=preview["exclusive_source_count"],
        shared_source_count=preview["shared_source_count"],
    )


@router.delete("/projects/{project_id}", response_model=ProjectDeleteResponse)
async def delete_project(
    project_id: str,
    delete_exclusive_sources: bool = Query(
        False, description="Delete sources that belong only to this project"
    ),
    ctx: AuthContext = Depends(get_auth_context),
):
    project = await _load_project_in_workspace(project_id, ctx)
    await _authorize_project_write(project, ctx)
    result = await project.delete(delete_exclusive_sources=delete_exclusive_sources)
    # Clean up membership rows so no dangling project_member remains.
    try:
        await repo_query(
            "DELETE project_member WHERE project = $project_id",
            {"project_id": ensure_record_id(project_id)},
        )
    except Exception as e:
        logger.warning(f"Failed to clear members for deleted project {project_id}: {e}")
    return ProjectDeleteResponse(
        message="Project deleted successfully",
        deleted_notes=result["deleted_notes"],
        deleted_sources=result["deleted_sources"],
        unlinked_sources=result["unlinked_sources"],
    )


def _recently_viewed_project(row: dict) -> RecentlyViewedResponse:
    return RecentlyViewedResponse(
        type="project",
        id=str(row.get("id", "")),
        title=row.get("title") or row.get("name") or "Untitled project",
        last_viewed_at=str(row.get("last_viewed_at", "")),
    )


def _recently_viewed_source(row: dict) -> RecentlyViewedResponse:
    return RecentlyViewedResponse(
        type="source",
        id=str(row.get("id", "")),
        title=row.get("title") or "Untitled source",
        last_viewed_at=str(row.get("last_viewed_at", "")),
    )


@router.post("/projects/{project_id}/sources/{source_id}")
async def add_source_to_project(
    project_id: str, source_id: str, ctx: AuthContext = Depends(get_auth_context)
):
    project = await _load_project_in_workspace(project_id, ctx)
    await _authorize_project_write(project, ctx)
    await Source.get(source_id)  # NotFoundError -> 404 via global handler
    existing = await repo_query(
        "SELECT * FROM reference WHERE out = $source_id AND in = $project_id",
        {
            "project_id": ensure_record_id(project_id),
            "source_id": ensure_record_id(source_id),
        },
    )
    if not existing:
        await repo_query(
            "RELATE $source_id->reference->$project_id",
            {
                "project_id": ensure_record_id(project_id),
                "source_id": ensure_record_id(source_id),
            },
        )
    return {"message": "Source linked to project successfully"}


@router.delete("/projects/{project_id}/sources/{source_id}")
async def remove_source_from_project(
    project_id: str, source_id: str, ctx: AuthContext = Depends(get_auth_context)
):
    project = await _load_project_in_workspace(project_id, ctx)
    await _authorize_project_write(project, ctx)
    await repo_query(
        "DELETE FROM reference WHERE out = $project_id AND in = $source_id",
        {
            "project_id": ensure_record_id(project_id),
            "source_id": ensure_record_id(source_id),
        },
    )
    return {"message": "Source removed from project successfully"}


@router.get("/recently-viewed", response_model=List[RecentlyViewedResponse])
async def get_recently_viewed(
    limit: int = Query(12, ge=1, le=50, description="Number of items to return"),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Recently viewed projects (in the active workspace) and sources, newest first."""
    try:
        projects = await repo_query(
            """
            SELECT id, name AS title, last_viewed_at
            FROM notebook
            WHERE workspace = $workspace_id
              AND last_viewed_at != NONE AND last_viewed_at != NULL
            ORDER BY last_viewed_at DESC
            LIMIT $limit
            """,
            {"workspace_id": ensure_record_id(ctx.workspace_id), "limit": limit},
        )
        sources = await repo_query(
            """
            SELECT id, title, last_viewed_at
            FROM source
            WHERE last_viewed_at != NONE AND last_viewed_at != NULL
            ORDER BY last_viewed_at DESC
            LIMIT $limit
            """,
            {"limit": limit},
        )
    except Exception as e:
        logger.exception(f"Error fetching recently viewed items: {e}")
        raise HTTPException(status_code=500, detail="Error fetching recently viewed items")

    items = [
        *[_recently_viewed_project(p) for p in projects],
        *[_recently_viewed_source(s) for s in sources],
    ]
    items.sort(key=lambda i: i.last_viewed_at, reverse=True)
    return items[:limit]
