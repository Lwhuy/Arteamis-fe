import asyncio
import traceback
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from langchain_core.runnables import RunnableConfig
from loguru import logger
from pydantic import BaseModel, Field

from api.deps import CtxDep
from api.source_permissions import (
    PermissionContext,
    get_permission_context,
    visible_source_ids,
)
from open_notebook.database.repository import ensure_record_id
from open_notebook.domain.notebook import (
    ChatSession,
    Note,
    Project,
    Source,
    SourceInsight,
)
from open_notebook.exceptions import (
    NotFoundError,
)
from open_notebook.graphs.chat import graph as chat_graph
from open_notebook.utils.graph_utils import get_session_message_count

router = APIRouter()


# Request/Response models
class CreateSessionRequest(BaseModel):
    notebook_id: str = Field(..., description="Notebook ID to create session for")
    title: Optional[str] = Field(None, description="Optional session title")
    model_override: Optional[str] = Field(
        None, description="Optional model override for this session"
    )


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = Field(None, description="New session title")
    model_override: Optional[str] = Field(
        None, description="Model override for this session"
    )


class ChatMessage(BaseModel):
    id: str = Field(..., description="Message ID")
    type: str = Field(..., description="Message type (human|ai)")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(None, description="Message timestamp")


class ChatSessionResponse(BaseModel):
    id: str = Field(..., description="Session ID")
    title: str = Field(..., description="Session title")
    notebook_id: Optional[str] = Field(None, description="Notebook ID")
    created: str = Field(..., description="Creation timestamp")
    updated: str = Field(..., description="Last update timestamp")
    message_count: Optional[int] = Field(
        None, description="Number of messages in session"
    )
    model_override: Optional[str] = Field(
        None, description="Model override for this session"
    )


class ChatSessionWithMessagesResponse(ChatSessionResponse):
    messages: List[ChatMessage] = Field(
        default_factory=list, description="Session messages"
    )


class ExecuteChatRequest(BaseModel):
    session_id: str = Field(..., description="Chat session ID")
    message: str = Field(..., description="User message content")
    context: Dict[str, Any] = Field(
        ..., description="Chat context with sources and notes"
    )
    model_override: Optional[str] = Field(
        None, description="Optional model override for this message"
    )


class ExecuteChatResponse(BaseModel):
    session_id: str = Field(..., description="Session ID")
    messages: List[ChatMessage] = Field(..., description="Updated message list")


class BuildContextRequest(BaseModel):
    notebook_id: str = Field(..., description="Notebook ID")
    context_config: Dict[str, Any] = Field(..., description="Context configuration")


class BuildContextResponse(BaseModel):
    context: Dict[str, Any] = Field(..., description="Built context data")
    token_count: int = Field(..., description="Estimated token count")
    char_count: int = Field(..., description="Character count")


class SuccessResponse(BaseModel):
    success: bool = Field(True, description="Operation success status")
    message: str = Field(..., description="Success message")


def _full_session_id(session_id: str) -> str:
    return (
        session_id
        if session_id.startswith("chat_session:")
        else f"chat_session:{session_id}"
    )


async def _get_owned_chat_session(repo: CtxDep, session_id: str) -> dict:
    """`chat_session` has no native `workspace` column (like `source`/`note` —
    see `_get_owned_source` in api/routers/projects.py) — it only belongs to a
    workspace transitively via the `refers_to` edge to a notebook in that
    workspace. A session created by api/routers/source_chat.py instead refers
    to a `source` (no `.workspace` field), so `out.workspace` evaluates to NONE
    for those edges and they never match here — this router only ever manages
    notebook-linked sessions, which is the only kind it creates. 404 (not 403)
    hides cross-workspace existence, matching ScopedRepository.get()'s
    no-oracle behavior.
    """
    rows = await repo.raw(
        # scoped-raw: chat_session has no native workspace column; ownership is
        # verified via the refers_to edge to a notebook in the caller's workspace
        "SELECT * FROM $sid WHERE id IN "
        "(SELECT VALUE in FROM refers_to WHERE out.workspace = $workspace_id)",
        {"sid": ensure_record_id(session_id)},
    )
    if not rows:
        raise NotFoundError(f"chat_session {session_id} not found")
    return rows[0]


async def _notebook_id_for_session(repo: CtxDep, session_id: str) -> Optional[str]:
    """Best-effort notebook id for an already workspace-verified session."""
    rows = await repo.raw(
        # scoped-raw: session_id is already workspace-verified by the caller
        # before this is invoked; only used to enrich the response payload
        "SELECT out FROM refers_to WHERE in = $session_id",
        {"session_id": ensure_record_id(session_id)},
    )
    return str(rows[0]["out"]) if rows else None


@router.get("/chat/sessions", response_model=List[ChatSessionResponse])
async def get_sessions(repo: CtxDep, notebook_id: str = Query(..., description="Notebook ID")):
    """Get all chat sessions for a notebook in the caller's active workspace."""
    try:
        await repo.get(notebook_id)  # workspace-checked; 404 on miss/cross-workspace

        rows = await repo.raw(
            # scoped-raw: chat_session has no native workspace column;
            # notebook_id is already workspace-verified via repo.get() above
            """
            SELECT * FROM (
                SELECT <-chat_session AS chat_session FROM refers_to
                WHERE out = $notebook_id
                FETCH chat_session
            )
            """,
            {"notebook_id": ensure_record_id(notebook_id)},
        )
        sessions = [row["chat_session"][0] for row in rows if row.get("chat_session")]

        results = []
        for session in sessions:
            session_id = str(session["id"])
            msg_count = await get_session_message_count(chat_graph, session_id)
            results.append(
                ChatSessionResponse(
                    id=session_id,
                    title=session.get("title") or "Untitled Session",
                    notebook_id=notebook_id,
                    created=str(session.get("created")),
                    updated=str(session.get("updated")),
                    message_count=msg_count,
                    model_override=session.get("model_override"),
                )
            )
        results.sort(key=lambda r: r.updated, reverse=True)
        return results
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Error fetching chat sessions: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching chat sessions: {str(e)}"
        )


@router.post("/chat/sessions", response_model=ChatSessionResponse)
async def create_session(request: CreateSessionRequest, repo: CtxDep):
    """Create a new chat session, linked to a notebook in the caller's active
    workspace. `chat_session` is workspace-inherited, so it's created via the
    domain model (ScopedRepository.create() rejects inherited tables) — but
    the notebook it's linked to is workspace-checked first."""
    try:
        await repo.get(request.notebook_id)  # workspace-checked; 404 on miss/cross-workspace

        session = ChatSession(
            title=request.title
            or f"Chat Session {asyncio.get_event_loop().time():.0f}",
            model_override=request.model_override,
        )
        await session.save()

        await session.relate_to_notebook(request.notebook_id)

        return ChatSessionResponse(
            id=session.id or "",
            title=session.title or "",
            notebook_id=request.notebook_id,
            created=str(session.created),
            updated=str(session.updated),
            message_count=0,
            model_override=session.model_override,
        )
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Error creating chat session: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error creating chat session: {str(e)}"
        )


@router.get(
    "/chat/sessions/{session_id}", response_model=ChatSessionWithMessagesResponse
)
async def get_session(session_id: str, repo: CtxDep):
    """Get a specific session with its messages. 404 if not in the caller's
    workspace (no cross-workspace oracle)."""
    try:
        full_session_id = _full_session_id(session_id)
        row = await _get_owned_chat_session(repo, full_session_id)  # 404 on cross-workspace
        session = ChatSession(**row)

        # Get session state from LangGraph to retrieve messages
        # Use sync get_state() in a thread since SqliteSaver doesn't support async
        thread_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_session_id}),
        )

        # Extract messages from state
        messages: list[ChatMessage] = []
        if thread_state and thread_state.values and "messages" in thread_state.values:
            for msg in thread_state.values["messages"]:
                messages.append(
                    ChatMessage(
                        id=getattr(msg, "id", f"msg_{len(messages)}"),
                        type=msg.type if hasattr(msg, "type") else "unknown",
                        content=msg.content if hasattr(msg, "content") else str(msg),
                        timestamp=None,  # LangChain messages don't have timestamps by default
                    )
                )

        notebook_id = await _notebook_id_for_session(repo, full_session_id)
        if not notebook_id:
            logger.warning(
                f"No notebook relationship found for session {session_id} - may be an orphaned session"
            )

        return ChatSessionWithMessagesResponse(
            id=session.id or "",
            title=session.title or "Untitled Session",
            notebook_id=notebook_id,
            created=str(session.created),
            updated=str(session.updated),
            message_count=len(messages),
            messages=messages,
            model_override=getattr(session, "model_override", None),
        )
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error fetching session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching session: {str(e)}")


@router.put("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(session_id: str, request: UpdateSessionRequest, repo: CtxDep):
    """Update session title. 404 on cross-workspace id (ownership-checked first)."""
    try:
        full_session_id = _full_session_id(session_id)
        await _get_owned_chat_session(repo, full_session_id)  # 404 on cross-workspace
        session = await ChatSession.get(full_session_id)

        update_data = request.model_dump(exclude_unset=True)

        if "title" in update_data:
            session.title = update_data["title"]

        if "model_override" in update_data:
            session.model_override = update_data["model_override"]

        await session.save()

        notebook_id = await _notebook_id_for_session(repo, full_session_id)
        msg_count = await get_session_message_count(chat_graph, full_session_id)

        return ChatSessionResponse(
            id=session.id or "",
            title=session.title or "",
            notebook_id=notebook_id,
            created=str(session.created),
            updated=str(session.updated),
            message_count=msg_count,
            model_override=session.model_override,
        )
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error updating session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating session: {str(e)}")


@router.delete("/chat/sessions/{session_id}", response_model=SuccessResponse)
async def delete_session(session_id: str, repo: CtxDep):
    """Delete a chat session. 404 on cross-workspace id (ownership-checked first)."""
    try:
        full_session_id = _full_session_id(session_id)
        await _get_owned_chat_session(repo, full_session_id)  # 404 on cross-workspace
        session = await ChatSession.get(full_session_id)

        await session.delete()

        return SuccessResponse(success=True, message="Session deleted successfully")
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error deleting session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting session: {str(e)}")


@router.post("/chat/execute", response_model=ExecuteChatResponse)
async def execute_chat(request: ExecuteChatRequest, repo: CtxDep):
    """Execute a chat request and get AI response. The session must belong to
    a notebook in the caller's active workspace (404 otherwise) — without
    this check a caller could inject messages/context into, and read the
    LangGraph checkpoint history of, another workspace's chat session merely
    by guessing its id."""
    try:
        full_session_id = _full_session_id(request.session_id)
        await _get_owned_chat_session(repo, full_session_id)  # 404 on cross-workspace
        session = await ChatSession.get(full_session_id)

        notebook_id = await _notebook_id_for_session(repo, full_session_id)
        notebook = Project(**await repo.get(notebook_id)) if notebook_id else None

        # Determine model override (per-request override takes precedence over session-level)
        model_override = (
            request.model_override
            if request.model_override is not None
            else getattr(session, "model_override", None)
        )

        # Get current state
        # Use sync get_state() in a thread since SqliteSaver doesn't support async
        current_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_session_id}),
        )

        # Prepare state for execution
        state_values = current_state.values if current_state else {}
        state_values["messages"] = state_values.get("messages", [])
        state_values["context"] = request.context
        state_values["notebook"] = notebook
        state_values["model_override"] = model_override

        # Add user message to state
        from langchain_core.messages import HumanMessage

        user_message = HumanMessage(content=request.message)
        state_values["messages"].append(user_message)

        # Execute chat graph in a thread so the synchronous LangGraph invoke
        # (SqliteSaver checkpoints are sync) doesn't block the event loop and
        # freeze the rest of the API while the LLM responds. Mirrors the
        # get_state() calls above.
        result = await asyncio.to_thread(
            chat_graph.invoke,
            input=state_values,  # type: ignore[arg-type]
            config=RunnableConfig(
                configurable={
                    "thread_id": full_session_id,
                    "model_id": model_override,
                }
            ),
        )

        # Update session timestamp
        await session.save()

        # Convert messages to response format
        messages: list[ChatMessage] = []
        for msg in result.get("messages", []):
            messages.append(
                ChatMessage(
                    id=getattr(msg, "id", f"msg_{len(messages)}"),
                    type=msg.type if hasattr(msg, "type") else "unknown",
                    content=msg.content if hasattr(msg, "content") else str(msg),
                    timestamp=None,
                )
            )

        return ExecuteChatResponse(session_id=request.session_id, messages=messages)
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        # Log detailed error with context for debugging
        logger.error(
            f"Error executing chat: {str(e)}\n"
            f"  Session ID: {request.session_id}\n"
            f"  Model override: {request.model_override}\n"
            f"  Traceback:\n{traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail=f"Error executing chat: {str(e)}")


@router.post("/chat/context", response_model=BuildContextResponse)
async def build_context(
    request: BuildContextRequest,
    repo: CtxDep,
    ctx: PermissionContext = Depends(get_permission_context),
):
    """Build context for a notebook based on context configuration."""
    try:
        # Workspace-checked; 404 on miss/cross-workspace (already gated in P5
        # via visible_source_ids' workspace filter -- kept unchanged here).
        notebook_row = await repo.get(request.notebook_id)
        notebook = Project(**notebook_row)

        # Allow-list of source ids the caller may view in this project (3-scope).
        # Also enforces workspace isolation: a notebook_id from another
        # workspace resolves to an empty set here (see
        # api.source_permissions.visible_source_ids), so nothing leaks.
        visible = set(await visible_source_ids(ctx, request.notebook_id))

        context_data: dict[str, list[dict[str, str]]] = {"sources": [], "notes": []}
        total_content = ""

        # Process context configuration if provided
        if request.context_config:
            # Process sources
            for source_id, status in request.context_config.get("sources", {}).items():
                if "not in" in status:
                    continue

                try:
                    # Add table prefix if not present
                    full_source_id = (
                        source_id
                        if source_id.startswith("source:")
                        else f"source:{source_id}"
                    )

                    # Skip sources the caller may not view (belt-and-braces
                    # with the set filter on the default-branch get_sources()
                    # call below).
                    if full_source_id not in visible:
                        continue

                    try:
                        source_rows = await repo.raw(
                            # scoped-raw: full_source_id is already verified to
                            # be in the caller's visible-in-workspace set
                            # (visible_source_ids) above
                            "SELECT * FROM $sid",
                            {"sid": ensure_record_id(full_source_id)},
                        )
                        if not source_rows:
                            continue
                        source = Source(**source_rows[0])
                    except Exception:
                        continue

                    if "insights" in status:
                        source_context = await source.get_context(context_size="short")
                        context_data["sources"].append(source_context)
                        total_content += str(source_context)
                    elif "full content" in status:
                        source_context = await source.get_context(context_size="long")
                        context_data["sources"].append(source_context)
                        total_content += str(source_context)
                except Exception as e:
                    logger.warning(f"Error processing source {source_id}: {str(e)}")
                    continue

            # Process notes
            for note_id, status in request.context_config.get("notes", {}).items():
                if "not in" in status:
                    continue

                try:
                    # Add table prefix if not present
                    full_note_id = (
                        note_id if note_id.startswith("note:") else f"note:{note_id}"
                    )
                    note = await Note.get(full_note_id)
                    if not note:
                        continue

                    if "full content" in status:
                        note_context = note.get_context(context_size="long")
                        context_data["notes"].append(note_context)
                        total_content += str(note_context)
                except Exception as e:
                    logger.warning(f"Error processing note {note_id}: {str(e)}")
                    continue
        else:
            # Default behavior - include all sources and notes with short context
            sources = await notebook.get_sources(viewer_source_ids=visible)
            try:
                insights_by_source = await SourceInsight.get_for_sources(
                    [source.id for source in sources if source.id]
                )
            except Exception as e:
                # Match the per-source fallback below: a hiccup fetching
                # insights shouldn't fail the whole context request.
                logger.warning(f"Error batch-fetching source insights: {str(e)}")
                insights_by_source = {}
            for source in sources:
                try:
                    source_context = await source.get_context(
                        context_size="short",
                        insights=insights_by_source.get(source.id or "", []),
                    )
                    context_data["sources"].append(source_context)
                    total_content += str(source_context)
                except Exception as e:
                    logger.warning(f"Error processing source {source.id}: {str(e)}")
                    continue

            notes = await notebook.get_notes()
            for note in notes:
                try:
                    note_context = note.get_context(context_size="short")
                    context_data["notes"].append(note_context)
                    total_content += str(note_context)
                except Exception as e:
                    logger.warning(f"Error processing note {note.id}: {str(e)}")
                    continue

        # Calculate character and token counts
        char_count = len(total_content)
        # Use token count utility if available
        try:
            from open_notebook.utils import token_count

            estimated_tokens = token_count(total_content) if total_content else 0
        except ImportError:
            # Fallback to simple estimation
            estimated_tokens = char_count // 4

        return BuildContextResponse(
            context=context_data, token_count=estimated_tokens, char_count=char_count
        )
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Error building context: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error building context: {str(e)}")
