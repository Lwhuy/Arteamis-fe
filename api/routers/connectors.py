"""Connectors Router — thin HTTP layer over api.connectors_service."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from loguru import logger

from api import connectors_service as svc
from api.models import (
    AuthorizeResponse,
    ConnectorItemResponse,
    ConnectorResponse,
    ImportRequest,
    ImportResponse,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.get("", response_model=list[ConnectorResponse])
async def list_connectors():
    return await svc.list_connectors_with_connections()


@router.get("/{provider}/authorize", response_model=AuthorizeResponse)
async def authorize(provider: str):
    try:
        return AuthorizeResponse(authorize_url=svc.build_authorize_url(provider))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{provider}/callback")
async def callback(provider: str, code: str = Query(...), state: str = Query(...)):
    try:
        await svc.handle_callback(provider, code, state)
        return RedirectResponse(svc.app_redirect(f"connected={provider}"))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"OAuth callback failed for {provider}: {e}")
        return RedirectResponse(svc.app_redirect(f"error=oauth_failed&provider={provider}"))


@router.get("/{provider}/items", response_model=list[ConnectorItemResponse])
async def list_items(provider: str, connection_id: str = Query(...)):
    try:
        return await svc.list_items(provider, connection_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{provider}/import", response_model=ImportResponse)
async def import_items(provider: str, body: ImportRequest):
    try:
        return await svc.import_items(
            provider, body.connection_id, body.item_ids, body.notebooks)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/connections/{connection_id}", status_code=204)
async def disconnect(connection_id: str):
    await svc.disconnect(connection_id)
