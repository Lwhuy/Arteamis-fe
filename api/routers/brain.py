from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.brain_models import (
    BrainGraphResponse,
    BrainRebuildRequest,
    BrainRebuildResponse,
    BrainStatusResponse,
)
from api.brain_service import get_brain_graph, get_brain_status, trigger_rebuild
from api.deps import get_auth_context, require_role
from api.security import AuthContext

router = APIRouter(prefix="/brain", tags=["brain"])

# Module-level so tests can override it via app.dependency_overrides.
owner_or_admin = require_role("owner", "admin")


@router.get("/graph", response_model=BrainGraphResponse)
async def get_graph(
    domain: Optional[str] = Query(default=None, description="Narrow to a domain subtree"),
    limit: int = Query(default=200, ge=1, le=1000, description="Max nodes (salience-ranked)"),
    ctx: AuthContext = Depends(get_auth_context),
) -> BrainGraphResponse:
    """Return the caller's active workspace's brain graph (nodes + edges)."""
    return await get_brain_graph(ctx, domain=domain, limit=limit)


@router.get("/status", response_model=BrainStatusResponse)
async def brain_status(
    ctx: AuthContext = Depends(get_auth_context),
) -> BrainStatusResponse:
    """Extraction coverage + build state for the active workspace (any member)."""
    return await get_brain_status(ctx)


@router.post("/rebuild", response_model=BrainRebuildResponse)
async def brain_rebuild(
    body: BrainRebuildRequest,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = Depends(owner_or_admin),
) -> BrainRebuildResponse:
    """Trigger a workspace brain rebuild (owner/admin only)."""
    command_id = await trigger_rebuild(ctx, body.mode)
    return BrainRebuildResponse(command_id=command_id)
