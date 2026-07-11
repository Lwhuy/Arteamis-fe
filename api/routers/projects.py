from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from api.deps import get_auth_context, require_role
from api.models import (
    ProjectCreate,
    ProjectResponse,
    RecentlyViewedResponse,  # noqa: F401 (used by Task 7)
)
from api.security import AuthContext
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Project
from open_notebook.exceptions import InvalidInputError

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
