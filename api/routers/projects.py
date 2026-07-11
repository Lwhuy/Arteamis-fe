from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from api.deps import CtxDep, require_role
from api.models import (
    ProjectCreate,
    ProjectDeletePreview,
    ProjectDeleteResponse,
    ProjectResponse,
    ProjectUpdate,
    RecentlyViewedResponse,
)
from open_notebook.database.repository import ensure_record_id
from open_notebook.domain.base import ObjectModel
from open_notebook.domain.notebook import Project
from open_notebook.exceptions import InvalidInputError, NotFoundError

router = APIRouter()


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


async def _authorize_project_write(repo: CtxDep, project_id: str) -> None:
    """Workspace owner/admin may write any project; otherwise the caller must be
    a project admin (active project_member row with role='admin').

    In a personal workspace repo.role is always "owner" (P2 invariant), so this
    always short-circuits on the first branch and project_member is never
    queried for a personal project.
    """
    if repo.role in {"owner", "admin"}:
        return
    rows = await repo.list(
        "project_member",
        where="project = $project AND user = $user AND role = 'admin' AND status = 'active'",
        vars={
            "project": ensure_record_id(project_id),
            "user": ensure_record_id(repo.user_id),
        },
    )
    if not rows:
        raise HTTPException(status_code=403, detail="Requires project admin")


async def _get_owned_source(repo: CtxDep, source_id: str) -> dict:
    """`source` has no native `workspace` column (§2 of the P6 scoping design) —
    it only belongs to a workspace transitively via a `reference` edge to some
    notebook in that workspace. 404 (not 403) hides cross-workspace existence,
    matching ScopedRepository.get()'s no-oracle behavior for natively-scoped
    tables. This also closes the P6 prep-design §3.10 gap: a source cannot be
    "adopted" into a caller's project merely by guessing its id — it must
    already belong to some notebook in the caller's own workspace.
    """
    rows = await repo.raw(
        # scoped-raw: source has no native workspace column; ownership is
        # verified via the reference edge to a notebook in the caller's workspace
        "SELECT * FROM $sid WHERE id IN "
        "(SELECT VALUE in FROM reference WHERE out.workspace = $workspace_id)",
        {"sid": ensure_record_id(source_id)},
    )
    if not rows:
        raise NotFoundError(f"source {source_id} not found")
    return rows[0]


@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    repo: CtxDep,
    archived: Optional[bool] = Query(None, description="Filter by archived status"),
    order_by: str = Query("updated desc", description="Order by field and direction"),
):
    """List projects for the caller's active workspace (personal or company) —
    the same code path for both, since ScopedRepository never reads `kind`."""
    validated_order_by = ObjectModel._validate_order_by(order_by)
    rows = await repo.raw(
        # scoped-raw: needs count(<-reference.in)/count(<-artifact.in) graph traversal
        "SELECT *, count(<-reference.in) AS source_count, count(<-artifact.in) AS note_count "
        f"FROM notebook WHERE workspace = $workspace_id ORDER BY {validated_order_by}",
    )
    if archived is not None:
        rows = [nb for nb in rows if nb.get("archived") == archived]
    return [_project_response_from_row(nb) for nb in rows]


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    repo: CtxDep,
    _auth=Depends(require_role("owner", "admin")),
):
    """Create a project in the caller's active workspace.

    require_role("owner","admin") gates a company workspace's plain members
    out, and naturally lets a personal-workspace owner create freely: P2's
    invariant is that a personal workspace has exactly one membership row and
    it is always role="owner", so no separate personal-workspace code path is
    needed here. workspace/owner are stamped server-side by ScopedRepository —
    a forged `workspace` in the request body is discarded.
    """
    try:
        # Constructed only for Project's own field validation (e.g. blank-name
        # rejection) — never saved directly; ScopedRepository.create() persists it.
        validated = Project(
            name=body.name,
            description=body.description,
            default_source_scope=body.default_source_scope or "personal",
        )
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))

    created = await repo.create(
        "notebook",
        {
            "name": validated.name,
            "description": validated.description,
            "owner": repo.user_id,
            "default_source_scope": validated.default_source_scope,
            "archived": False,
        },
    )

    # Seed the creator as the sole admin project_member. This row is only ever
    # consulted for authorization when the workspace is a company workspace and
    # P4's invite flow adds more members; for a personal project it is a
    # harmless no-op since repo.role == "owner" already authorizes everything.
    try:
        await repo.create(
            "project_member",
            {
                "project": created["id"],
                "user": repo.user_id,
                "role": "admin",
                "status": "active",
            },
        )
    except Exception as e:
        logger.warning(f"Failed to seed admin member for project {created.get('id')}: {e}")

    return _project_response_from_row({**created, "source_count": 0, "note_count": 0})


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, repo: CtxDep):
    """Get one project. 404 if not in the caller's workspace (no cross-workspace
    oracle) — including when the "other" workspace is someone else's personal
    workspace."""
    await repo.get(project_id)  # workspace-checked; NotFoundError (404) on miss/cross-workspace
    rows = await repo.raw(
        # scoped-raw: needs count(<-reference.in)/count(<-artifact.in) graph traversal
        "SELECT *, count(<-reference.in) AS source_count, count(<-artifact.in) AS note_count "
        "FROM $rid WHERE workspace = $workspace_id",
        {"rid": ensure_record_id(project_id)},
    )
    if not rows:
        raise NotFoundError(f"Project {project_id} not found")
    # Best-effort write-on-read stamp; never fail a read. Scoped so a guessed
    # cross-workspace id can't be used to write anywhere.
    try:
        await repo.raw(
            # scoped-raw: last_viewed_at stamp on an already workspace-verified project
            "UPDATE $rid SET last_viewed_at = time::now() WHERE workspace = $workspace_id",
            {"rid": ensure_record_id(project_id)},
        )
    except Exception as e:
        logger.warning(f"Failed to stamp last_viewed_at for project {project_id}: {e}")
    return _project_response_from_row(rows[0])


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    repo: CtxDep,
):
    """Update a project. 404 on cross-workspace id; 403 unless the caller is a
    workspace owner/admin or an active project admin."""
    await repo.get(project_id)  # workspace-checked first (404 before any 403)
    await _authorize_project_write(repo, project_id)

    patch = {
        k: v
        for k, v in {
            "name": body.name,
            "description": body.description,
            "archived": body.archived,
            "default_source_scope": body.default_source_scope,
        }.items()
        if v is not None
    }
    if not patch:
        raise InvalidInputError("No updatable fields provided")
    if "name" in patch and not patch["name"].strip():
        raise InvalidInputError("Notebook name cannot be empty")

    await repo.update(project_id, patch)  # ownership-checked again → 404 on cross-workspace
    return await get_project(project_id, repo)


@router.get(
    "/projects/{project_id}/delete-preview", response_model=ProjectDeletePreview
)
async def get_project_delete_preview(project_id: str, repo: CtxDep):
    row = await repo.get(project_id)  # workspace-checked; 404 on miss/cross-workspace
    await _authorize_project_write(repo, project_id)
    project = Project(**row)
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
    repo: CtxDep,
    delete_exclusive_sources: bool = Query(
        False, description="Delete sources that belong only to this project"
    ),
):
    row = await repo.get(project_id)  # workspace-checked; 404 on miss/cross-workspace
    await _authorize_project_write(repo, project_id)
    project = Project(**row)
    result = await project.delete(delete_exclusive_sources=delete_exclusive_sources)
    # Clean up membership rows so no dangling project_member remains.
    try:
        await repo.raw(
            # scoped-raw: bulk cleanup for an already workspace-verified project
            "DELETE project_member WHERE project = $rid",
            {"rid": ensure_record_id(project_id)},
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
async def add_source_to_project(project_id: str, source_id: str, repo: CtxDep):
    await repo.get(project_id)  # workspace-checked; 404 on miss/cross-workspace
    await _authorize_project_write(repo, project_id)
    await _get_owned_source(repo, source_id)  # 404 unless already workspace-owned
    existing = await repo.raw(
        # scoped-raw: reference-edge existence check; project + source already
        # workspace-verified above
        "SELECT * FROM reference WHERE out = $source_id AND in = $project_id",
        {
            "project_id": ensure_record_id(project_id),
            "source_id": ensure_record_id(source_id),
        },
    )
    if not existing:
        await repo.raw(
            # scoped-raw: RELATE has no WHERE to inject workspace into; both
            # ids already workspace-verified above
            "RELATE $source_id->reference->$project_id",
            {
                "project_id": ensure_record_id(project_id),
                "source_id": ensure_record_id(source_id),
            },
        )
    return {"message": "Source linked to project successfully"}


@router.delete("/projects/{project_id}/sources/{source_id}")
async def remove_source_from_project(project_id: str, source_id: str, repo: CtxDep):
    await repo.get(project_id)  # workspace-checked; 404 on miss/cross-workspace
    await _authorize_project_write(repo, project_id)
    await repo.raw(
        # scoped-raw: unlink edge; project already workspace-verified above
        "DELETE FROM reference WHERE out = $project_id AND in = $source_id",
        {
            "project_id": ensure_record_id(project_id),
            "source_id": ensure_record_id(source_id),
        },
    )
    return {"message": "Source removed from project successfully"}


@router.get("/recently-viewed", response_model=List[RecentlyViewedResponse])
async def get_recently_viewed(
    repo: CtxDep,
    limit: int = Query(12, ge=1, le=50, description="Number of items to return"),
):
    """Recently viewed projects and sources in the active workspace, newest
    first. The source half used to run unscoped (P6 prep-design §3.10 gap) —
    now scoped via the same reference-edge join as `_get_owned_source`."""
    try:
        projects = await repo.raw(
            # scoped-raw: recently viewed projects in caller's workspace
            """
            SELECT id, name AS title, last_viewed_at
            FROM notebook
            WHERE workspace = $workspace_id
              AND last_viewed_at != NONE AND last_viewed_at != NULL
            ORDER BY last_viewed_at DESC
            LIMIT $limit
            """,
            {"limit": limit},
        )
        sources = await repo.raw(
            # scoped-raw: source has no native workspace column; scoped via the
            # reference edge to a notebook in the caller's workspace
            """
            SELECT id, title, last_viewed_at
            FROM source
            WHERE last_viewed_at != NONE AND last_viewed_at != NULL
              AND id IN (SELECT VALUE in FROM reference WHERE out.workspace = $workspace_id)
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
