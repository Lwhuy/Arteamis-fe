import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger

from api.brain_models import (
    BrainGraphResponse,
    BrainRebuildRequest,
    BrainRebuildResponse,
    BrainStatusResponse,
)
from api.brain_service import (
    ask_brain,
    get_brain_graph,
    get_brain_status,
    trigger_rebuild,
)
from api.deps import get_auth_context, require_role
from api.models import AskRequest
from api.security import AuthContext
from api.source_permissions import PermissionContext, get_permission_context
from open_notebook.ai.models import Model, model_manager

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


@router.post("/ask")
async def ask_brain_endpoint(
    ask_request: AskRequest,
    ctx: PermissionContext = Depends(get_permission_context),
):
    """Graph-aware RAG over the active workspace's brain (SSE stream, any member)."""
    strategy_model = await Model.get(ask_request.strategy_model)
    answer_model = await Model.get(ask_request.answer_model)
    final_answer_model = await Model.get(ask_request.final_answer_model)

    if not strategy_model:
        raise HTTPException(
            status_code=400,
            detail=f"Strategy model {ask_request.strategy_model} not found",
        )
    if not answer_model:
        raise HTTPException(
            status_code=400,
            detail=f"Answer model {ask_request.answer_model} not found",
        )
    if not final_answer_model:
        raise HTTPException(
            status_code=400,
            detail=f"Final answer model {ask_request.final_answer_model} not found",
        )
    if not await model_manager.get_embedding_model():
        raise HTTPException(
            status_code=400,
            detail="Ask the Brain requires an embedding model. Please configure one in the Models section.",
        )

    async def event_stream():
        try:
            async for event in ask_brain(
                ctx,
                ask_request.question,
                ask_request.strategy_model,
                ask_request.answer_model,
                ask_request.final_answer_model,
            ):
                yield f"data: {event.model_dump_json()}\n\n"
        except Exception as e:  # defensive: ask_brain already converts errors to events
            logger.error(f"Error in /brain/ask stream: {str(e)}")
            error_payload = {"type": "error", "message": str(e), "cited_node_ids": []}
            yield f"data: {json.dumps(error_payload)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
