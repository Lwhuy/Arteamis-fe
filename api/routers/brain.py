from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.brain_models import BrainGraphResponse
from api.brain_service import get_brain_graph
from api.deps import get_auth_context
from api.security import AuthContext

router = APIRouter(prefix="/brain", tags=["brain"])


@router.get("/graph", response_model=BrainGraphResponse)
async def get_graph(
    domain: Optional[str] = Query(default=None, description="Narrow to a domain subtree"),
    limit: int = Query(default=200, ge=1, le=1000, description="Max nodes (salience-ranked)"),
    ctx: AuthContext = Depends(get_auth_context),
) -> BrainGraphResponse:
    """Return the caller's active workspace's brain graph (nodes + edges)."""
    return await get_brain_graph(ctx, domain=domain, limit=limit)
