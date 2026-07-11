"""Business logic for external source connectors. The router is a thin shell
over this module. All provider I/O is delegated to BaseConnector adapters."""
import os
from typing import List, Optional

from loguru import logger

from api.command_service import CommandService
from open_notebook.database.repository import ensure_record_id, repo_delete
from open_notebook.domain.connection import Connection
from open_notebook.domain.connectors import (
    COMING_SOON,
    CONNECTOR_REGISTRY,
    get_connector,
    oauth_state,
)
from open_notebook.domain.notebook import Asset, Source

# IMPORTANT: create sources via the DOMAIN layer (Source + CommandService),
# exactly like api/routers/sources.py does — NOT via api.sources_service.SourceService,
# which is a client-side HTTP wrapper (api_client → httpx to the running API) and would
# make the API call itself over HTTP. The domain path is the correct in-process route.


def _api_url() -> str:
    return os.getenv("CONNECTORS_API_URL", "http://localhost:5055").rstrip("/")


def _app_url() -> str:
    return os.getenv("CONNECTORS_APP_URL", "http://localhost:3000").rstrip("/")


def redirect_uri_for(provider: str) -> str:
    return f"{_api_url()}/api/connectors/{provider}/callback"


def app_redirect(query: str) -> str:
    return f"{_app_url()}/connections?{query}"


def _connection_public(conn: Connection) -> dict:
    return {
        "id": conn.id,
        "provider": conn.provider,
        "account_label": conn.account_label,
        "status": conn.status,
        "created": conn.created.isoformat() if conn.created else None,
    }


async def _provider_connections(provider: str) -> List[Connection]:
    return await Connection.get_by_provider(provider)


def list_connectors() -> List[dict]:
    """Live connectors first (with per-provider status), then coming-soon cards.

    Note: connection counts are resolved lazily by the router via
    `list_connectors_with_connections`. This sync function reports config/live
    status without a DB round-trip so it stays unit-testable."""
    out: List[dict] = []
    for provider, cls in CONNECTOR_REGISTRY.items():
        adapter = cls()
        out.append({
            "provider": provider,
            "display_name": adapter.display_name,
            "description": adapter.description,
            "status": "configured" if adapter.is_configured() else "available",
            "connections": [],
        })
    for cs in COMING_SOON:
        out.append({**cs, "status": "coming_soon", "connections": []})
    return out


async def list_connectors_with_connections() -> List[dict]:
    base = list_connectors()
    for entry in base:
        if entry["status"] == "coming_soon":
            continue
        conns = await _provider_connections(entry["provider"])
        entry["connections"] = [_connection_public(c) for c in conns]
        if conns:
            entry["status"] = "connected"
    return base


def build_authorize_url(provider: str) -> str:
    adapter = get_connector(provider)
    if not adapter.is_configured():
        raise ValueError(f"{provider} OAuth app is not configured (missing env vars)")
    state = oauth_state.create_state()
    return adapter.authorize_url(state, redirect_uri_for(provider))


async def handle_callback(provider: str, code: str, state: str) -> Connection:
    if not oauth_state.consume_state(state):
        raise ValueError("Invalid or expired OAuth state")
    adapter = get_connector(provider)
    token = await adapter.exchange_code(code, redirect_uri_for(provider))
    conn = Connection(
        provider=provider,
        account_label=token.account_label or adapter.display_name,
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        token_expires_at=token.expires_at,
        scopes=token.scopes,
        status="connected",
    )
    await conn.save()
    return conn


async def list_items(provider: str, connection_id: str) -> List[dict]:
    adapter = get_connector(provider)
    conn = await Connection.get(connection_id)
    items = await adapter.list_items(conn)
    return [
        {"id": i.id, "kind": i.kind, "title": i.title, "subtitle": i.subtitle,
         "mime": i.mime, "modified_at": i.modified_at}
        for i in items
    ]


async def _ingest_doc(doc, notebooks: Optional[List[str]]) -> str:
    """Create a Source from an ImportedDoc and queue async processing, mirroring
    the async path of api/routers/sources.py. Returns the command id.

    `doc.file_path` (binary download) → upload-style content_state; otherwise
    `doc.content` → text content_state. The background `process_source` command
    reads content_state and runs extraction/embedding; the worker
    (`make worker-start`) must be running or the job queues forever.
    """
    # Ensure the process_source command is registered before submitting.
    import commands.source_commands  # noqa: F401
    from commands.source_commands import SourceProcessingInput

    if doc.file_path:
        asset = Asset(file_path=doc.file_path)
        content_state = {"file_path": doc.file_path, "delete_source": True}
    else:
        asset = None
        content_state = {"content": doc.content or ""}

    source = Source(title=doc.title or "Untitled", topics=[], asset=asset)
    await source.save()

    try:
        for notebook_id in notebooks or []:
            await source.add_to_notebook(notebook_id)

        command_input = SourceProcessingInput(
            source_id=str(source.id),
            content_state=content_state,
            # SourceProcessingInput.notebook_ids is a non-optional List[str]; the
            # router path normalizes None->[] via a model_validator, so we do the
            # same here (importing without a target notebook is the default).
            notebook_ids=notebooks or [],
            transformations=[],
            embed=True,
        )
        command_id = await CommandService.submit_command_job(
            "open_notebook", "process_source", command_input.model_dump()
        )
        source.command = ensure_record_id(command_id)
        await source.save()
        return command_id
    except Exception:
        # Roll back the half-created source so a failed queue submission doesn't
        # leave an orphan record (mirrors the sources router's cleanup).
        try:
            await source.delete()
        except Exception:  # noqa: BLE001
            pass
        raise


async def import_items(
    provider: str, connection_id: str, item_ids: List[str],
    notebooks: Optional[List[str]] = None,
) -> dict:
    adapter = get_connector(provider)
    conn = await Connection.get(connection_id)
    all_items = {i.id: i for i in await adapter.list_items(conn)}
    accepted, failed = [], []
    for item_id in item_ids:
        item = all_items.get(item_id)
        if item is None:
            failed.append({"item_id": item_id, "error": "item not found"})
            continue
        try:
            doc = await adapter.fetch_content(conn, item)
            await _ingest_doc(doc, notebooks)
            accepted.append(item_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"connector import failed for {provider}/{item_id}: {e}")
            failed.append({"item_id": item_id, "error": str(e)})
    return {"accepted": accepted, "failed": failed}


async def disconnect(connection_id: str) -> None:
    await repo_delete(ensure_record_id(connection_id))
